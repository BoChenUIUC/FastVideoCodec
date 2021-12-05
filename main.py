from __future__ import print_function
import os
import sys
import time
import math
import random

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

from models import get_codec_model,parallel_compression,update_training,compress_whole_video
from models import load_state_dict_whatever, load_state_dict_all, load_state_dict_only

class VideoDataset(Dataset):
    def __init__(self, root_dir, frame_size=None):
        self._dataset_dir = os.path.join(root_dir)
        self._frame_size = frame_size
        self._total_frames = 0 # Storing file names in object 
        
        self.get_file_names()
        self._num_files = len(self.__file_names)
        
        self.reset()
        
    def reset(self):
        self._curr_counter = 0
        self._frame_counter = -1 # Count the number of frames used per file
        self._file_counter = -1 # Count the number of files used
        self._dataset_nums = [] # Number of frames to be considered from each file (records+files)
        self._clip = [] # hold video frames
        self._cur_file_names = list(self.__file_names)
        
    @property
    def data(self):
        self._curr_counter+=1
        return self.__getitem__(self._curr_counter)
        
    def __getitem__(self, idx):
        # Get the next dataset if frame number is more than table count
        if not len(self._dataset_nums) or self._frame_counter >= self._dataset_nums[self._file_counter]-1: 
            self.current_file = self._cur_file_names.pop() # get one filename
            cap = cv2.VideoCapture(self.current_file)
            # Check if camera opened successfully
            if (cap.isOpened()== False):
                print("Error opening video stream or file")
            # Read until video is completed
            while(cap.isOpened()):
                # Capture frame-by-frame
                ret, img = cap.read()
                if ret != True:break
                # skip black frames
                if np.sum(img) == 0:continue
                img = Image.fromarray(img)
                if self._frame_size is not None:
                    img = img.resize(self._frame_size) 
                self._clip.append(img)
            self._file_counter +=1
            self._dataset_nums.append(len(self._clip))
            self._frame_counter = 0
        else:
            self._frame_counter+=1
        return self._clip[self._frame_counter],self._frame_counter==self._dataset_nums[self._file_counter]-1
        
    def get_file_names(self):
        print("[log] Looking for files in", self._dataset_dir)  
        self.__file_names = []
        for fn in os.listdir(self._dataset_dir):
            fn = fn.strip("'")
            if fn.split('.')[-1] == 'mp4':
                self.__file_names.append(self._dataset_dir + '/' + fn)
            break
        print("[log] Number of files found {}".format(len(self.__file_names)))  
        
    def __len__(self):
        if not self._total_frames:
            self.count_frames()
        return self._total_frames
        
    def count_frames(self):
        # Count total frames 
        self._total_frames = 0
        for file_name in self.__file_names:
            cap = cv2.VideoCapture(file_name)
            # Check if camera opened successfully
            if (cap.isOpened()== False):
                print("Error opening video stream or file")
            # Read until video is completed
            while(cap.isOpened()):
                # Capture frame-by-frame
                ret, img = cap.read()
                if ret != True:break
                if np.sum(img) == 0:continue
                self._total_frames+=1
            # When everything done, release the video capture object
            cap.release()
        #print("[log] Total frames: ", self._total_frames)
        
class FrameDataset(Dataset):
    def __init__(self, root_dir, frame_size=None):
        self._dataset_dir = os.path.join(root_dir,'vimeo_septuplet','sequences')
        self._train_list_dir = os.path.join(root_dir,'vimeo_septuplet','sep_trainlist.txt')
        self._frame_size = frame_size
        self._total_frames = 0 # Storing file names in object
        self.get_septuplet_names()
        
    def get_septuplet_names(self):
        print("[log] Looking for septuplets in", self._dataset_dir) 
        self.__septuplet_names = []
        with open(self._train_list_dir,'r') as f:
            for line in f:
                line = line.strip()
                self.__septuplet_names += [self._dataset_dir + '/' + line]
        print("[log] Number of septuplets found {}".format(len(self.__septuplet_names)))
                
    def __len__(self):
        return len(self.__septuplet_names)*7
        
    def reset(self):
        return
        
    def __getitem__(self, idx):
        frame_idx,tuplet_idx = idx%7+1,idx//7
        base_dir = self.__septuplet_names[tuplet_idx]
        img_dir = base_dir+'/'+f'im{frame_idx}.png'
        img = Image.open(img_dir).convert('RGB')
        if self._frame_size is not None:
            img = img.resize(self._frame_size) 
        return img,frame_idx==7

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

def save_checkpoint(state, is_best, directory, CODEC_NAME):
    import shutil
    torch.save(state, f'{directory}/{CODEC_NAME}/{CODEC_NAME}-1024P_ckpt.pth')
    if is_best:
        shutil.copyfile(f'{directory}/{CODEC_NAME}/{CODEC_NAME}-1024P_ckpt.pth',
                        f'{directory}/{CODEC_NAME}/{CODEC_NAME}-1024P_best.pth')

# OPTION
BACKUP_DIR = 'backup'
CODEC_NAME = 'SPVC'
RESUME_CODEC_PATH = f'backup/{CODEC_NAME}/{CODEC_NAME}-1024P_best.pth'
LEARNING_RATE = 0.0001
WEIGHT_DECAY = 5e-4
BEGIN_EPOCH = 1
END_EPOCH = 10

####### Check backup directory, create if necessary
# ---------------------------------------------------------------
if not os.path.exists(BACKUP_DIR):
    os.makedirs(BACKUP_DIR)

####### Create model
seed = int(time.time())
#seed = int(0)
torch.manual_seed(seed)
use_cuda = True
if use_cuda:
    os.environ['CUDA_VISIBLE_DEVICES'] = '0,1' # TODO: add to config e.g. 0,1,2,3
    torch.cuda.manual_seed(seed)

# codec model .
model = get_codec_model(CODEC_NAME)
pytorch_total_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
print('Total number of trainable codec parameters: {}'.format(pytorch_total_params))

####### Create optimizer
# ---------------------------------------------------------------
parameters = [p for n, p in model.named_parameters() if (not n.endswith(".quantiles"))]
aux_parameters = [p for n, p in model.named_parameters() if n.endswith(".quantiles")]
optimizer = torch.optim.Adam([{'params': parameters},{'params': aux_parameters, 'lr': 10*LEARNING_RATE}], lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY)
# initialize best score
best_score = 0 
best_codec_score = [1,0,0]

####### Load yowo model
# ---------------------------------------------------------------
# try to load codec model 
if CODEC_NAME in ['x265', 'x264', 'RAW']:
    # nothing to load
    print("No need to load for ", CODEC_NAME)
elif CODEC_NAME in ['SCVC']:
    # load what exists
    print("Load whatever exists for",CODEC_NAME)
    pretrained_model_path = "/home/monet/research/YOWO/backup/ucf24/yowo_ucf24_16f_SPVC_best.pth"
    checkpoint = torch.load(pretrained_model_path)
    load_state_dict_whatever(model_codec, checkpoint['state_dict'])
    del checkpoint
elif RESUME_CODEC_PATH and os.path.isfile(RESUME_CODEC_PATH):
    print("Loading for ", CODEC_NAME, 'from',RESUME_CODEC_PATH)
    checkpoint = torch.load(RESUME_CODEC_PATH)
    BEGIN_EPOCH = checkpoint['epoch'] + 1
    best_codec_score = checkpoint['score'][1:4]
    load_state_dict_all(model, checkpoint['state_dict'])
    print("Loaded model codec score: ", checkpoint['score'])
    del checkpoint
else:
    print("Cannot load model codec", CODEC_NAME)
    exit(1)
print("===================================================================")
        
def train(epoch, model, train_dataset, optimizer, test_dataset, best_codec_score):
    aux_loss_module = AverageMeter()
    img_loss_module = AverageMeter()
    be_loss_module = AverageMeter()
    psnr_module = AverageMeter()
    msssim_module = AverageMeter()
    all_loss_module = AverageMeter()
    scaler = torch.cuda.amp.GradScaler(enabled=True)
    batch_size = 7
    ds_size = len(train_dataset)
    
    model.train()
    update_training(model,epoch)
    
    train_iter = tqdm(range(ds_size))
    data = []
    batch_idx = 0
    for data_idx,_ in enumerate(train_iter):
        frame,eof = train_dataset[data_idx]
        data.append(transforms.ToTensor()(frame))
        if len(data) < batch_size and not eof:
            continue
        data = torch.stack(data, dim=0).cuda()
        l = data.size(0)-1
        
        # run model
        _,img_loss_list,bpp_est_list,aux_loss_list,psnr_list,msssim_list,_ = parallel_compression(model,data,True)
        
        # aggregate loss
        be_loss = torch.stack(bpp_est_list,dim=0).mean(dim=0)
        aux_loss = torch.stack(aux_loss_list,dim=0).mean(dim=0)
        img_loss = torch.stack(img_loss_list,dim=0).mean(dim=0)
        psnr = torch.stack(psnr_list,dim=0).mean(dim=0)
        msssim = torch.stack(msssim_list,dim=0).mean(dim=0)
        loss = model.loss(img_loss,be_loss,aux_loss)
        
        # record loss
        aux_loss_module.update(aux_loss.cpu().data.item(), l)
        img_loss_module.update(img_loss.cpu().data.item(), l)
        be_loss_module.update(be_loss.cpu().data.item(), l)
        psnr_module.update(psnr.cpu().data.item(),l)
        msssim_module.update(msssim.cpu().data.item(), l)
        all_loss_module.update(loss.cpu().data.item(), l)
        
        # backward
        scaler.scale(loss).backward()
        # update model after compress each video
        if eof:
            scaler.step(optimizer)
            scaler.update()
            optimizer.zero_grad()
            
        # show result
        train_iter.set_description(
            f"{data_idx:6}. "
            f"IL: {img_loss_module.val:.2f} ({img_loss_module.avg:.2f}). "
            f"BE: {be_loss_module.val:.2f} ({be_loss_module.avg:.2f}). "
            f"AX: {aux_loss_module.val:.2f} ({aux_loss_module.avg:.2f}). "
            f"AL: {all_loss_module.val:.2f} ({all_loss_module.avg:.2f}). "
            f"P: {psnr_module.val:.2f} ({psnr_module.avg:.2f}). "
            f"M: {msssim_module.val:.4f} ({msssim_module.avg:.4f}). ")

        # clear result every 1000 batches
        if batch_idx % 1000 == 0 and batch_idx>0: # From time to time, reset averagemeters to see improvements
            img_loss_module.reset()
            aux_loss_module.reset()
            be_loss_module.reset()
            all_loss_module.reset()
            psnr_module.reset()
            msssim_module.reset()   

        
        # ---------EVALUATE---------
        if batch_idx % 5000 == 0 and batch_idx > 0:
            best_codec_score = test(epoch, model, test_dataset, best_codec_score)
        # --------------------------
            
        # clear input
        data = []
        batch_idx += 1
      
    best_codec_score = test(epoch, model, test_dataset, best_codec_score)
        
    return best_codec_score
    
def test(epoch, model, test_dataset, best_codec_score=None):
    aux_loss_module = AverageMeter()
    img_loss_module = AverageMeter()
    ba_loss_module = AverageMeter()
    psnr_module = AverageMeter()
    msssim_module = AverageMeter()
    all_loss_module = AverageMeter()
    ds_size = len(test_dataset)
    
    model.eval()
    
    fP,bP = 6,6
    GoP = fP+bP+1
    
    data = []
    test_iter = tqdm(range(ds_size))
    for data_idx,_ in enumerate(test_iter):
        frame,eof = test_dataset[data_idx]
        data.append(transforms.ToTensor()(frame))
        if len(data) < GoP and not eof:
            continue
            
        with torch.no_grad():
            data = torch.stack(data, dim=0).cuda()
            l = data.size(0)
            
            # compress GoP
            if l>fP+1:
                com_imgs,img_loss_list1,_,aux_loss_list1,psnr_list1,msssim_list1,bpp_act_list1 = parallel_compression(model,torch.flip(data[:fP+1],[0]),True)
                data[fP:fP+1] = com_imgs[0:1]
                _,img_loss_list2,_,aux_loss_list2,psnr_list2,msssim_list2,bpp_act_list2 = parallel_compression(model,data[fP:],False)
                img_loss_list = img_loss_list1[::-1] + img_loss_list2
                aux_loss_list = aux_loss_list1[::-1] + aux_loss_list2
                psnr_list = psnr_list1[::-1] + psnr_list2
                msssim_list = msssim_list1[::-1] + msssim_list2
                bpp_act_list = bpp_act_list1[::-1] + bpp_act_list2
            else:
                _,img_loss_list,_,aux_loss_list,psnr_list,msssim_list,bpp_act_list = parallel_compression(model,torch.flip(data,[0]),True)
                
            # aggregate loss
            ba_loss = torch.stack(bpp_act_list,dim=0).mean(dim=0)
            aux_loss = torch.stack(aux_loss_list,dim=0).mean(dim=0)
            img_loss = torch.stack(img_loss_list,dim=0).mean(dim=0)
            psnr = torch.stack(psnr_list,dim=0).mean(dim=0)
            msssim = torch.stack(msssim_list,dim=0).mean(dim=0)
            loss = model.loss(img_loss,ba_loss,aux_loss)
            
            # record loss
            aux_loss_module.update(aux_loss.cpu().data.item(), l)
            img_loss_module.update(img_loss.cpu().data.item(), l)
            ba_loss_module.update(ba_loss.cpu().data.item(), l)
            psnr_module.update(psnr.cpu().data.item(),l)
            msssim_module.update(msssim.cpu().data.item(), l)
            all_loss_module.update(loss.cpu().data.item(), l)
        
        # show result
        test_iter.set_description(
            f"{data_idx:6}. "
            f"IL: {img_loss_module.val:.2f} ({img_loss_module.avg:.2f}). "
            f"BA: {ba_loss_module.val:.2f} ({ba_loss_module.avg:.2f}). "
            f"AX: {aux_loss_module.val:.2f} ({aux_loss_module.avg:.2f}). "
            f"AL: {all_loss_module.val:.2f} ({all_loss_module.avg:.2f}). "
            f"P: {psnr_module.val:.2f} ({psnr_module.avg:.2f}). "
            f"M: {msssim_module.val:.4f} ({msssim_module.avg:.4f}). ")
            
        # clear input
        data = []
        
    test_dataset.reset()
    
    # evaluate
    score = [ba_loss_module.avg,psnr_module.avg,msssim_module.avg]
    is_best = isinstance(best_codec_score,list) and (score[0] <= best_codec_score[0]) and (score[1] >= best_codec_score[1])
    if is_best:
        print("New best score is achieved: ", score, ". Previous score was: ", best_codec_score)
        best_codec_score = score
    state = {'epoch': epoch, 'state_dict': model.state_dict(), 'score': score}
    save_checkpoint(state, is_best, BACKUP_DIR, CODEC_NAME)
    print('Weights are saved to backup directory: %s' % (BACKUP_DIR))
    
    return best_codec_score
        
def test_x26x(test_dataset,name='x264'):
    print('Benchmarking:',name)
    ds_size = len(test_dataset)
    
    for Q in [15,19,23,27]:
        data = []
        ba_loss_module = AverageMeter()
        psnr_module = AverageMeter()
        msssim_module = AverageMeter()
        test_iter = tqdm(range(ds_size))
        for data_idx,_ in enumerate(test_iter):
            frame,eof = test_dataset[data_idx]
            data.append(frame)
            if not eof:
                continue
            l = len(data)
                
            psnr_list,msssim_list,bpp_act_list = compress_whole_video(name,data,Q,*test_dataset._frame_size)
            
            # aggregate loss
            ba_loss = torch.stack(bpp_act_list,dim=0).mean(dim=0)
            psnr = torch.stack(psnr_list,dim=0).mean(dim=0)
            msssim = torch.stack(msssim_list,dim=0).mean(dim=0)
            
            # record loss
            ba_loss_module.update(ba_loss.cpu().data.item(), l)
            psnr_module.update(psnr.cpu().data.item(),l)
            msssim_module.update(msssim.cpu().data.item(), l)
            
            # show result
            test_iter.set_description(
                f"{data_idx:6}. "
                f"BA: {ba_loss_module.val:.2f} ({ba_loss_module.avg:.2f}). "
                f"P: {psnr_module.val:.2f} ({psnr_module.avg:.2f}). "
                f"M: {msssim_module.val:.4f} ({msssim_module.avg:.4f}). ")
                
            # clear input
            data = []
            
        test_dataset.reset()
                        
def adjust_learning_rate(optimizer, epoch):
    """Sets the learning rate to the initial LR decayed by 10 every 30 epochs"""
    LEARNING_RATE = 1e-4
    LR_DECAY_RATE = 0.1
    STEPS = []
    lr_new = LEARNING_RATE * (LR_DECAY_RATE ** (sum(epoch >= np.array(STEPS))))
    for param_group in optimizer.param_groups:
        param_group['lr'] = lr_new
    return lr_new
    
####### Load dataset
train_dataset = FrameDataset('../dataset/vimeo')
test_dataset = VideoDataset('../dataset/UVG', frame_size=(256,256))

# optionaly try x264,x265
#test_x26x(test_dataset,'x264')
#test_x26x(test_dataset,'x265')

test(model, test_dataset)
exit(0)

for epoch in range(BEGIN_EPOCH, END_EPOCH + 1):
    # Adjust learning rate
    r = adjust_learning_rate(optimizer, epoch)
    
    # Train and test model
    print('training at epoch %d, r=%.2f' % (epoch,r))
    best_codec_score = train(epoch, model, train_dataset, optimizer, test_dataset, best_codec_score)