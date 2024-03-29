from __future__ import print_function
import os
import sys
import time
import math
import random
import argparse

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
import torch.backends.cudnn as cudnn
from torchvision import datasets, transforms
from torch.utils.data import Dataset
from torch.cuda.amp import autocast as autocast

import cv2
import numpy as np
from tqdm import tqdm
from PIL import Image

from models import get_codec_model,parallel_compression
from models import load_state_dict_whatever, load_state_dict_all, load_state_dict_only

from dataset import VideoDataset, FrameDataset

parser = argparse.ArgumentParser(description='PyTorch EAVC Training')
parser.add_argument('--dataset', type=str, default='UVG', choices=['UVG','MCL-JCV','UVG/2k','MCL-JCV/2k'],
                    help='evaluating dataset (default: UVG)')
parser.add_argument('--batch_size', default=8, type=int,
                    help="batch size")
parser.add_argument('--evaluate', action='store_true',
                    help='evaluate model on validation set')
parser.add_argument('--evolve', action='store_true',
                    help='evolve model')
parser.add_argument('--codec', type=str, default='Base',
                    help='name of codec')
parser.add_argument('--device', default=0, type=int,
                    help="GPU ID")
parser.add_argument('--epoch', type=int, nargs='+', default=[0,100],
                    help='Begin and end epoch')
parser.add_argument('--lr', type=float, default=0.0001,
                    help='Learning rate')
parser.add_argument('--width', type=int, default=256,
                    help='Frame width') 
parser.add_argument('--height', type=int, default=256,
                    help='Frame height') 
parser.add_argument('--compression_level', default=0, type=int,
                    help="Compression level")
parser.add_argument('--max_files', default=0, type=int,
                    help="Maximum loaded files")
parser.add_argument('--evolve_rounds', default=1, type=int,
                    help="Maximum evolving rounds")
parser.add_argument('--resume', type=str, default='',
                    help='Resume path')
parser.add_argument('--norm', default=2, type=int,
                    help="Norm type")
parser.add_argument('--alpha', type=float, default=100,
                    help='Controlling norm scale')

args = parser.parse_args()

# OPTION
CODEC_NAME = args.codec
SAVE_DIR = f'backup/{CODEC_NAME}'
loss_type = 'P'
compression_level = args.compression_level # 0-7
if args.resume == '':
    RESUME_CODEC_PATH = f'backup/{CODEC_NAME}/{CODEC_NAME}-{compression_level}{loss_type}_ckpt.pth'
else:
    RESUME_CODEC_PATH = args.resume
LEARNING_RATE = args.lr
WEIGHT_DECAY = 5e-4
BEGIN_EPOCH = args.epoch[0]
END_EPOCH = args.epoch[1]
WARMUP_EPOCH = 5
device = args.device
STEPS = []

if not os.path.exists(SAVE_DIR):
    os.makedirs(SAVE_DIR)

####### Create model
# seed = int(time.time())
seed = int(0)
torch.manual_seed(seed)
use_cuda = True
if use_cuda:
    os.environ['CUDA_VISIBLE_DEVICES'] = '0,1' # TODO: add to config e.g. 0,1,2,3
    torch.cuda.manual_seed(seed)

# codec model .
model = get_codec_model(CODEC_NAME, 
                        loss_type=loss_type, 
                        compression_level=compression_level,
                        use_split=False)
model = model.cuda(device)
pytorch_total_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
print('Total number of trainable codec parameters: {}'.format(pytorch_total_params))

# initialize best score
best_codec_score = 100

####### Load yowo model
# ---------------------------------------------------------------
# try to load codec model 
if CODEC_NAME in ['SSF-Official']:
    print('Official model loaded.')
elif RESUME_CODEC_PATH and os.path.isfile(RESUME_CODEC_PATH):
    print("Loading all for ", CODEC_NAME, 'from',RESUME_CODEC_PATH)
    checkpoint = torch.load(RESUME_CODEC_PATH,map_location=torch.device('cuda:'+str(device)))
    # BEGIN_EPOCH = checkpoint['epoch'] + 1
    if isinstance(checkpoint['score'],float):
        best_codec_score = checkpoint['score']
    # load_state_dict_all(model, checkpoint['state_dict'])
    load_state_dict_whatever(model, checkpoint['state_dict'])
    print("Loaded model codec score: ", checkpoint['score'])
    if 'stats' in checkpoint:
        print(checkpoint['stats'])
    del checkpoint
elif 'Base' in CODEC_NAME:
    # load what exists
    pretrained_model_path = f'DVC/snapshot/256.model'
    checkpoint = torch.load(pretrained_model_path,map_location=torch.device('cuda:'+str(device)))
    if 'state_dict' in checkpoint.keys():
        load_state_dict_whatever(model, checkpoint['state_dict'])
        if isinstance(checkpoint['score'],float):
            best_codec_score = checkpoint['score']
    else:
        # model.load_state_dict(checkpoint)
        load_state_dict_whatever(model, checkpoint)
    del checkpoint
    print("Load baseline",pretrained_model_path)
else:
    print("Cannot load model codec", RESUME_CODEC_PATH)
print("===================================================================")

class AverageMeter(object):
    """Computes and stores the average and current value"""

    def __init__(self):
        self.reset()

    def reset(self):
        self.val = 0
        self.avg = 0
        self.sum = 0
        self.count = 0
 
    def update(self, val, n=1):
        self.val = val
        self.sum += val * n
        self.count += n
        self.avg = self.sum / self.count
        
def train(epoch, model, train_dataset, best_codec_score, test_dataset):
    # create optimizer
    if 'ELFVC-SP' not in model.name:
        parameters = [p for n, p in model.named_parameters()]
        lr = LEARNING_RATE
        optimizer = torch.optim.Adam([{'params': parameters}], lr=lr, weight_decay=WEIGHT_DECAY)
    else:
        optimizer = model.optim_parameters(epoch,LEARNING_RATE,WEIGHT_DECAY)
    # Adjust learning rate
    adjust_learning_rate(optimizer, epoch)

    img_loss_module = AverageMeter()
    be_loss_module = AverageMeter()
    be_res_loss_module = AverageMeter()
    psnr_module = AverageMeter()
    all_loss_module = AverageMeter()
    aux_loss_module = AverageMeter()
    aux2_loss_module = AverageMeter()
    aux3_loss_module = AverageMeter()
    aux4_loss_module = AverageMeter()
    scaler = torch.cuda.amp.GradScaler(enabled=True)
    ds_size = len(train_dataset)
    
    model.train()
    train_loader = torch.utils.data.DataLoader(train_dataset, batch_size=args.batch_size, shuffle=True, 
                                               num_workers=8, drop_last=True, pin_memory=True)
    
    train_iter = tqdm(train_loader)
    for batch_idx,data in enumerate(train_iter):
        data = data.cuda(device)
        
        # run model
        _,loss,img_loss,be_loss,be_res_loss,psnr,_,aux_loss,aux_loss2,aux_loss3,aux_loss4 = parallel_compression(args,model,data,True, batch_idx=batch_idx)

        # record loss
        all_loss_module.update(img_loss + be_loss)
        img_loss_module.update(img_loss)
        be_loss_module.update(be_loss)
        be_res_loss_module.update(be_res_loss)
        if not math.isinf(psnr):
            psnr_module.update(psnr)
        aux_loss_module.update(aux_loss)
        aux2_loss_module.update(aux_loss2)
        aux3_loss_module.update(aux_loss3)
        aux4_loss_module.update(aux_loss4)
        
        # backward
        scaler.scale(loss).backward()
        scaler.step(optimizer)
        scaler.update()
        optimizer.zero_grad()

            
        # show result
        train_iter.set_description(
            f"{epoch} {batch_idx:6}. "
            f"L:{all_loss_module.val:.4f} ({all_loss_module.avg:.4f}). "
            f"I:{img_loss_module.val:.4f} ({img_loss_module.avg:.4f}). "
            f"B:{be_loss_module.val:.4f} ({be_loss_module.avg:.4f}). "
            # f"P:{psnr_module.val:.2f} ({psnr_module.avg:.2f}). "
            f"FS:{aux_loss_module.val:.4f} ({aux_loss_module.avg:.4f}). "
            f"FQ:{aux2_loss_module.val:.4f} ({aux2_loss_module.avg:.4f}). "
            f"RS:{aux3_loss_module.val:.4f} ({aux3_loss_module.avg:.4f}). "
            f"RQ:{aux4_loss_module.val:.4f} ({aux4_loss_module.avg:.4f}). ")
            
        if batch_idx % 5000 == 0 and batch_idx>0:
            if True:
                print('')
                score, stats = test(epoch, model, test_dataset)
                
                is_best = score <= best_codec_score
                if is_best:
                    print("New best", stats, "Score:", score, ". Previous: ", best_codec_score)
                    best_codec_score = score
                else:
                    print('')
                state = {'epoch': epoch, 'state_dict': model.state_dict(), 'score': score, 'stats': stats}
                save_checkpoint(state, is_best, SAVE_DIR, CODEC_NAME, loss_type, compression_level)
                model.train()
            else:
                print('')
                state = {'epoch': epoch, 'state_dict': model.state_dict(), 'score': best_codec_score}
                save_checkpoint(state, False, SAVE_DIR, CODEC_NAME, loss_type, compression_level)

        # clear result every 1000 batches
        if batch_idx % 5000 == 0 and batch_idx>0: # From time to time, reset averagemeters to see improvements
            img_loss_module.reset()
            aux_loss_module.reset()
            be_loss_module.reset()
            be_res_loss_module.reset()
            all_loss_module.reset()
            psnr_module.reset()
            aux2_loss_module.reset()
            aux3_loss_module.reset()
            aux4_loss_module.reset()
    return best_codec_score
    
def test(epoch, model, test_dataset, level=0, doEvolve=False, optimizer=None):
    model.eval()
    img_loss_module = AverageMeter()
    ba_loss_module = AverageMeter()
    psnr_module = AverageMeter()
    all_loss_module = AverageMeter()
    aux_loss_module = AverageMeter()
    aux2_loss_module = AverageMeter()
    aux3_loss_module = AverageMeter()
    aux4_loss_module = AverageMeter()
    ds_size = len(test_dataset)
    
    fP,bP = 15,0
    GoP = fP+bP+1
    
    data = []
    test_iter = tqdm(range(ds_size))
    eof = False
    for data_idx,_ in enumerate(test_iter):
        if doEvolve and (data_idx == 0 or eof):
            evolve(model, test_dataset, data_idx, ds_size)
        frame,eof = test_dataset[data_idx]
        data.append((frame))
        if len(data) < GoP and not eof:
            continue
            
        with torch.no_grad():
            data = torch.stack(data, dim=0).cuda(device)
            l = data.size(0)
            
            # compress GoP
            com_imgs,loss,img_loss,be_loss,be_res_loss,psnr,_,aux_loss,aux_loss2,aux_loss3,aux_loss4 = parallel_compression(args,model,data,True,level)
            ba_loss_module.update(be_loss, l)
            psnr_module.update(psnr,l)
            all_loss_module.update(float(loss),l)
            img_loss_module.update(img_loss,l)
            aux_loss_module.update(aux_loss,l)
            aux2_loss_module.update(aux_loss2,l)
            aux3_loss_module.update(aux_loss3,l)
            aux4_loss_module.update(aux_loss4,l)
                
        # show result
        test_iter.set_description(
            f"{epoch} {data_idx:6}. "
            f"B:{ba_loss_module.val:.4f} ({ba_loss_module.avg:.4f}). "
            f"P:{psnr_module.val:.4f} ({psnr_module.avg:.4f}). "
            f"L:{all_loss_module.val:.4f} ({all_loss_module.avg:.4f}). "
            f"IL:{img_loss_module.val:.4f} ({img_loss_module.avg:.4f}). "
            f"FS:{aux_loss_module.val:.4f} ({aux_loss_module.avg:.4f}). "
            f"FQ:{aux2_loss_module.val:.4f} ({aux2_loss_module.avg:.4f}). "
            f"RS:{aux3_loss_module.val:.4f} ({aux3_loss_module.avg:.4f}). "
            f"RQ:{aux4_loss_module.val:.4f} ({aux4_loss_module.avg:.4f}). ")
            
        # clear input
        data = []
        if doEvolve and eof:
            checkpoint = torch.load(RESUME_CODEC_PATH,map_location=torch.device('cuda:'+str(device)))
            load_state_dict_all(model, checkpoint['state_dict'])
    test_dataset.reset()
    return ba_loss_module.avg+img_loss_module.avg, [ba_loss_module.avg,psnr_module.avg]

def evolve(model, test_dataset, start, end):
    # should check if evolved version is available
    # if not, training will keep the best version for this video
    scaler = torch.cuda.amp.GradScaler(enabled=True)
    model.train()
    fP,bP = 6,6
    GoP = fP+bP+1
    min_loss = 100
    for encoder_name in ['motion_encoder','res_encoder']:
        parameters = [p for n, p in model.named_parameters() if encoder_name in n]
        # this learning rate to avoid overfitting
        optimizer = torch.optim.Adam([{'params': parameters}], lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
        converge_count = shrink_count = 0
        for _ in range(30):
            img_loss_module = AverageMeter()
            ba_loss_module = AverageMeter()
            psnr_module = AverageMeter()
            all_loss_module = AverageMeter()
            data = []
            test_iter = tqdm(range(start, end))
            for _,data_idx in enumerate(test_iter):
                frame,eof = test_dataset[data_idx]
                data.append(transforms.ToTensor()(frame))
                if len(data) < GoP and not eof:
                    continue
                    
                data = torch.stack(data, dim=0).cuda(device)
                l = data.size(0)
                
                # compress GoP
                if l>fP+1:
                    com_imgs,loss1,img_loss,be_loss,be_res_loss,psnr,_,aux_loss,aux_loss2,_,_ = parallel_compression(args,model,torch.flip(data[:fP+1],[0]),True,level)
                    ba_loss_module.update(be_loss, fP+1)
                    psnr_module.update(psnr,fP+1)
                    all_loss_module.update(loss1.cpu().data.item() if loss1 else loss1,fP)
                    img_loss_module.update(img_loss,fP)
                    data[fP:fP+1] = com_imgs[0:1]
                    com_imgs,loss2,img_loss,be_loss,be_res_loss,psnr,_,aux_loss,aux_loss2,_,_ = parallel_compression(args,model,data[fP:],False,level)
                    ba_loss_module.update(be_loss, l-fP-1)
                    psnr_module.update(psnr,l-fP-1)
                    all_loss_module.update(loss2.cpu().data.item() if loss2 else loss2,l-fP-1)
                    img_loss_module.update(img_loss,l-fP-1)
                    loss = (loss1 * fP + loss2 * (l - fP - 1))/(l - 1)
                else:
                    com_imgs,loss,img_loss,be_loss,be_res_loss,psnr,_,aux_loss,aux_loss2,_,_ = parallel_compression(args,model,torch.flip(data,[0]),True,level)
                    ba_loss_module.update(be_loss, l)
                    psnr_module.update(psnr,l)
                    all_loss_module.update(loss.cpu().data.item() if loss else loss,l-1)
                    img_loss_module.update(img_loss,l-1)

                # backward
                if loss:
                    scaler.scale(loss).backward()
                    scaler.step(optimizer)
                    scaler.update()
                    optimizer.zero_grad()
                        
                # show result
                test_iter.set_description(
                    f"{encoder_name} {data_idx:6} {converge_count} {shrink_count}. "
                    f"B:{ba_loss_module.val:.4f} ({ba_loss_module.avg:.4f}). "
                    f"P:{psnr_module.val:.4f} ({psnr_module.avg:.4f}). "
                    f"L:{all_loss_module.val:.4f} ({all_loss_module.avg:.4f}). "
                    f"IL:{img_loss_module.val:.4f} ({img_loss_module.avg:.4f}). ")
                    
                # clear input
                data = []

                if eof:
                    test_dataset._frame_counter = -1
                    break

            if all_loss_module.avg < min_loss:
                min_loss = all_loss_module.avg
                best_state_dict = model.state_dict()
                converge_count = 0
            else:
                converge_count += 1
                if converge_count == 3:
                    if shrink_count < 2:
                        shrink_learning_rate(optimizer)
                        converge_count = 0
                        shrink_count += 1
                    else:
                        break
    load_state_dict_all(model, best_state_dict)
    model.eval()
                        
def adjust_learning_rate(optimizer, epoch):
    """Sets the learning rate to the initial LR decayed by 10 every 30 epochs"""
    LR_DECAY_RATE = 0.1
    r = (LR_DECAY_RATE ** (sum(epoch >= np.array(STEPS))))
    for param_group in optimizer.param_groups:
        param_group['lr'] *= r
    return r

def shrink_learning_rate(optimizer):
    LR_DECAY_RATE = 0.1
    for param_group in optimizer.param_groups:
        param_group['lr'] *= LR_DECAY_RATE

def save_checkpoint(state, is_best, directory, CODEC_NAME, loss_type, compression_level):
    import shutil
    epoch = state['epoch']
    torch.save(state, f'{directory}/{CODEC_NAME}-{compression_level}{loss_type}_ckpt.pth')
    # shutil.copyfile(f'{directory}/{CODEC_NAME}-{compression_level}{loss_type}_ckpt.pth',
    #                 f'{directory}/{CODEC_NAME}-{compression_level}{loss_type}.{epoch}.pth')
    if is_best:
        shutil.copyfile(f'{directory}/{CODEC_NAME}-{compression_level}{loss_type}_ckpt.pth',
                        f'{directory}/{CODEC_NAME}-{compression_level}{loss_type}_best.pth')
          
train_dataset = FrameDataset('../dataset/vimeo', frame_size=256) 
test_dataset = VideoDataset(f'../dataset/{args.dataset}', (args.height, args.width), args.max_files)
if args.evolve:
    print('Evolution files:', args.max_files)
    args.evaluate = True
if args.evaluate:
    for level in range(8):
        score, stats = test(0, model, test_dataset, level, args.evolve)
        print(score, stats)
        if model.name not in ['ELFVC-L']:break
    exit(0)

for epoch in range(BEGIN_EPOCH, END_EPOCH + 1):
    best_codec_score = train(epoch, model, train_dataset, best_codec_score, test_dataset)
    
    score, stats = test(epoch, model, test_dataset)
    
    is_best = score <= best_codec_score
    if is_best:
        print("New best", stats, "Score:", score, ". Previous: ", best_codec_score)
        best_codec_score = score
    state = {'epoch': epoch, 'state_dict': model.state_dict(), 'score': score, 'stats': stats}
    save_checkpoint(state, is_best, SAVE_DIR, CODEC_NAME, loss_type, compression_level)
    print('Weights are saved to backup directory: %s' % (SAVE_DIR), 'score:',score)