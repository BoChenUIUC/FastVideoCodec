from __future__ import print_function
import os
import io
import sys
import time
import math
import random
import numpy as np
import subprocess as sp
import shlex
import cv2

import torch
import torch.nn as nn
import torch.utils.data
import torch.nn.functional as F
import torch.optim as optim
from torch.autograd import Variable
import torch.backends.cudnn as cudnn
from torch.autograd import Function
from torchvision import transforms
from compressai.layers import GDN
from entropy_models import RecProbModel,MeanScaleHyperPriors,RPM
from compressai.models.waseda import Cheng2020Attention
import pytorch_msssim
from PIL import Image
import torchac

def get_codec_model(name, loss_type='P', compression_level=2, noMeasure=True, use_split=True):
    if name in ['RLVC','DVC','RAW','RLVC2']:
        model_codec = IterPredVideoCodecs(name,loss_type=loss_type,compression_level=compression_level,noMeasure=noMeasure,use_split=use_split)
    elif 'SPVC' in name:
        model_codec = SPVC(name,loss_type=loss_type,compression_level=compression_level,noMeasure=noMeasure,use_split=use_split)
    elif name in ['SCVC']:
        model_codec = SCVC(name,loss_type=loss_type,compression_level=compression_level,noMeasure=noMeasure)
    elif name in ['AE3D']:
        model_codec = AE3D(name,loss_type=loss_type,compression_level=compression_level,noMeasure=noMeasure,use_split=use_split)
    elif name in ['x264','x265']:
        model_codec = StandardVideoCodecs(name)
    elif name in ['DVC-pretrained']:
        model_codec = get_DVC_pretrained(compression_level)
    elif 'LSVC' in name:
        model_codec = LSVC(name,loss_type=loss_type,compression_level=compression_level,use_split=use_split)
    else:
        print('Cannot recognize codec:', name)
        exit(1)
    return model_codec

def compress_video(model, frame_idx, cache, startNewClip):
    if model.name in ['MLVC','RLVC','DVC']:
        compress_video_sequential(model, frame_idx, cache, startNewClip)
    elif model.name in ['x265','x264']:
        compress_video_group(model, frame_idx, cache, startNewClip)
    elif model.name in ['SCVC','AE3D'] or 'SPVC' in model.name:
        compress_video_batch(model, frame_idx, cache, startNewClip)
            
def init_training_params(model):
    model.r_img, model.r_bpp, model.r_aux = 1,1,1
    model.stage = 'REC'
    
    psnr_list = [256,512,1024,2048,4096]
    msssim_list = [8,16,32,64]
    I_lvl_list = [37,32,27,22,17]
    model.r = psnr_list[model.compression_level] if model.loss_type == 'P' else msssim_list[model.compression_level]
    model.I_level = I_lvl_list[model.compression_level] # [37,32,27,22] poor->good quality
    # print(f'MSE/MSSSIM multiplier:{model.r}, BPG level:{model.I_level}, channels:{model.channels}')
    
    model.fmt_enc_str = "{0:.3f} {1:.3f} {2:.3f} {3:.3f} {4:.3f} {5:.3f}"
    model.fmt_dec_str = "{0:.3f} {1:.3f} {2:.3f}"
    model.meters = {'E-FL':AverageMeter(),'E-MV':AverageMeter(),'eEMV':AverageMeter(),
                    'E-MC':AverageMeter(),'E-RES':AverageMeter(),'eERES':AverageMeter(),
                    'E-NET':AverageMeter(),
                    'D-MV':AverageMeter(),'eDMV':AverageMeter(),'D-MC':AverageMeter(),
                    'D-RES':AverageMeter(),'eDRES':AverageMeter(),'D-NET':AverageMeter()}
    model.bitscounter = {'M':AverageMeter(),'R':AverageMeter()}
    
def showTimer(model):
    enc = sum([val.avg if 'E-' in key else 0 for key,val in model.meters.items()])
    dec = sum([val.avg if 'D-' in key else 0 for key,val in model.meters.items()])
    enc_str = model.fmt_enc_str.format(model.meters['E-FL'].avg,model.meters['E-MV'].avg,
        model.meters['E-MC'].avg,model.meters['E-RES'].avg,
        model.bitscounter['M'].avg,model.bitscounter['R'].avg)
    dec_str = model.fmt_dec_str.format(model.meters["D-MV"].avg,model.meters["D-MC"].avg,
        model.meters["D-RES"].avg)
    # print(enc,enc_str)
    # print(dec,dec_str)
    return enc_str,dec_str,enc,dec
    
def update_training(model, epoch, batch_idx=None, warmup_epoch=30):
    # warmup with all gamma set to 1
    # optimize for bpp,img loss and focus only reconstruction loss
    # optimize bpp and app loss only
    
    # setup training weights
    if epoch <= warmup_epoch:
        model.r_img, model.r_bpp, model.r_aux = 1,1,1
        model.stage = 'REC' # WP->MC->REC
    else:
        model.r_img, model.r_bpp, model.r_aux = 1,1,1
    
    model.epoch = epoch
    print('Update training:',model.r_img, model.r_bpp, model.r_aux, model.stage)
        
def compress_whole_video(name, raw_clip, Q, width=256,height=256):
    imgByteArr = io.BytesIO()
    fps = 25
    #Q = 27#15,19,23,27
    GOP = 13
    output_filename = 'tmp/videostreams/output.mp4'
    if name == 'x265':
        cmd = f'/usr/bin/ffmpeg -y -s {width}x{height} -pixel_format bgr24 -f rawvideo -r {fps} -i pipe: -vcodec libx265 -pix_fmt yuv420p -preset veryfast -tune zerolatency -x265-params "crf={Q}:keyint={GOP}:verbose=1" {output_filename}'
    elif name == 'x264':
        cmd = f'/usr/bin/ffmpeg -y -s {width}x{height} -pixel_format bgr24 -f rawvideo -r {fps} -i pipe: -vcodec libx264 -pix_fmt yuv420p -preset veryfast -tune zerolatency -crf {Q} -g {GOP} -bf 2 -b_strategy 0 -sc_threshold 0 -loglevel debug {output_filename}'
    else:
        print('Codec not supported')
        exit(1)
    # bgr24, rgb24, rgb?
    #process = sp.Popen(shlex.split(f'/usr/bin/ffmpeg -y -s {width}x{height} -pixel_format bgr24 -f rawvideo -r {fps} -i pipe: -vcodec {libname} -pix_fmt yuv420p -crf 24 {output_filename}'), stdin=sp.PIPE)
    process = sp.Popen(shlex.split(cmd), stdin=sp.PIPE, stdout=sp.DEVNULL, stderr=sp.STDOUT)
    for img in raw_clip:
        process.stdin.write(np.array(img).tobytes())
    # Close and flush stdin
    process.stdin.close()
    # Wait for sub-process to finish
    process.wait()
    # Terminate the sub-process
    process.terminate()
    # check video size
    video_size = os.path.getsize(output_filename)*8
    # Use OpenCV to read video
    clip = []
    cap = cv2.VideoCapture(output_filename)
    # Check if camera opened successfully
    if (cap.isOpened()== False):
        print("Error opening video stream or file")
    # Read until video is completed
    while(cap.isOpened()):
        # Capture frame-by-frame
        ret, img = cap.read()
        if ret != True:break
        clip.append(transforms.ToTensor()(img))
    # When everything done, release the video capture object
    cap.release()
    assert len(clip) == len(raw_clip), f'Clip size mismatch {len(clip)} {len(raw_clip)}'
    # create cache
    psnr_list = [];msssim_list = [];bpp_act_list = []
    bpp = video_size*1.0/len(clip)/(height*width)
    for i in range(len(clip)):
        Y1_raw = transforms.ToTensor()(raw_clip[i]).unsqueeze(0)
        Y1_com = clip[i].unsqueeze(0)
        psnr_list += [PSNR(Y1_raw, Y1_com)]
        msssim_list += [MSSSIM(Y1_raw, Y1_com)]
        bpp_act_list += torch.FloatTensor([bpp])
        
    return psnr_list,msssim_list,bpp_act_list
        
# depending on training or testing
# the compression time should be recorded accordinglly
def compress_video_sequential(model, frame_idx, cache, startNewClip):
    # process the involving GOP
    # if process in order, some frames need later frames to compress
    L = len(cache['clip'])
    if startNewClip:
        # create cache
        cache['bpp_est'] = {}
        cache['img_loss'] = {}
        cache['aux'] = {}
        cache['bpp_act'] = {}
        cache['msssim'] = {}
        cache['psnr'] = {}
        cache['end_of_batch'] = [False for _ in range(L)]
        cache['hidden'] = None
        cache['max_proc'] = -1
        # the first frame to be compressed in a video
    assert frame_idx>=1, 'Frame index less than 1'
    if cache['max_proc'] >= frame_idx-1:
        cache['max_seen'] = frame_idx-1
    else:
        ranges, cache['max_seen'], cache['max_proc'] = index2GOP(frame_idx-1, len(cache['clip']))
        for _range in ranges:
            prev_j = -1
            for loc,j in enumerate(_range):
                progressive_compression(model, j, prev_j, cache, loc==1, loc>=2)
                prev_j = j
        
def compress_video_batch(model, frame_idx, cache, startNewClip):
    # process the involving GOP
    # how to deal with backward P frames?
    # if process in order, some frames need later frames to compress
    L = len(cache['clip'])
    if startNewClip:
        # create cache
        cache['bpp_est'] = {}
        cache['img_loss'] = {}
        cache['aux'] = {}
        cache['bpp_act'] = {}
        cache['msssim'] = {}
        cache['psnr'] = {}
        cache['end_of_batch'] = [False for _ in range(L)]
        cache['max_proc'] = -1
    if cache['max_proc'] >= frame_idx-1:
        cache['max_seen'] = frame_idx-1
    else:
        ranges, cache['max_seen'], cache['max_proc'] = index2GOP(frame_idx-1, L)
        parallel_compression(model, ranges, cache)
      
def progressive_compression(model, i, prev, cache, P_flag, RPM_flag):
    # frame shape
    _,h,w = cache['clip'][0].shape
    # frames to be processed
    Y0_com = cache['clip'][prev].unsqueeze(0) if prev>=0 else None
    Y1_raw = cache['clip'][i].unsqueeze(0)
    # hidden variables
    if P_flag:
        hidden = model.init_hidden(h,w)
    else:
        hidden = cache['hidden']
    Y1_com,hidden,bpp_est,img_loss,aux_loss,bpp_act,psnr,msssim = model(Y0_com, Y1_raw, hidden, RPM_flag)
    cache['hidden'] = hidden
    cache['clip'][i] = Y1_com.detach().squeeze(0).cuda(0)
    cache['img_loss'][i] = img_loss.cuda(0)
    cache['aux'][i] = aux_loss.cuda(0)
    cache['bpp_est'][i] = bpp_est.cuda(0)
    cache['psnr'][i] = psnr.cuda(0)
    cache['msssim'][i] = msssim.cuda(0)
    cache['bpp_act'][i] = bpp_act.cuda(0)
    cache['end_of_batch'][i] = (i%4==0)
    #print(i,float(bpp_est),float(bpp_act),float(psnr))
    # we can record PSNR wrt the distance to I-frame to show error propagation)
        
def parallel_compression(model, data, compressI=False):
    img_loss_list = []; aux_loss_list = []; bpp_est_list = []; psnr_list = []; msssim_list = []; bpp_act_list = []; bpp_res_est_list = []
    
    if compressI:
        name = f"{model.name}-{model.compression_level}-{model.loss_type}-{os.getpid()}"
        x_hat, bpp_est, img_loss, aux_loss, bpp_act, psnr, msssim = I_compression(data[0:1], model.I_level, model_name=name)
        bpp_est_list += [bpp_est.to(data.device)]
        bpp_act_list += [bpp_act.to(data.device)]
        psnr_list += [psnr.to(data.device)]
        data[0:1] = x_hat
    
    
    # P compression, not including I frame
    if data.size(0) > 1: 
        if 'SPVC' in model.name:
            if model.training:
                _, bpp_est, bpp_res_est, img_loss, aux_loss, bpp_act, psnr, msssim = model(data.detach())
            else:
                _, bpp_est, img_loss, aux_loss, bpp_act, psnr, msssim = model(data.detach())
            for pos in range(data.size(0)-1):
                img_loss_list += [img_loss[pos].to(data.device)]
                aux_loss_list += [aux_loss[pos].to(data.device)]
                bpp_est_list += [bpp_est[pos].to(data.device)]
                if model.training:
                    bpp_res_est_list += [bpp_res_est[pos].to(data.device)]
                bpp_act_list += [bpp_act[pos].to(data.device)]
                psnr_list += [psnr[pos].to(data.device)]
                msssim_list += [msssim[pos].to(data.device)]
        elif model.name in ['DVC','RLVC','RLVC2']:
            B,_,H,W = data.size()
            hidden = model.init_hidden(H,W,data.device)
            mv_prior_latent = res_prior_latent = None
            x_prev = data[0:1]
            x_hat_list = []
            for i in range(1,B):
                if model.training:
                    x_prev,hidden,bpp_est,bpp_res_est,img_loss,aux_loss,bpp_act,psnr,msssim,mv_prior_latent,res_prior_latent = \
                        model(x_prev, data[i:i+1], hidden, i>1,mv_prior_latent,res_prior_latent)
                else:
                    x_prev,hidden,bpp_est,img_loss,aux_loss,bpp_act,psnr,msssim,mv_prior_latent,res_prior_latent = \
                        model(x_prev, data[i:i+1], hidden, i>1,mv_prior_latent,res_prior_latent)
                x_prev = x_prev.detach()
                img_loss_list += [img_loss.to(data.device)]
                aux_loss_list += [aux_loss.to(data.device)]
                bpp_est_list += [bpp_est.to(data.device)]
                bpp_act_list += [bpp_act.to(data.device)]
                psnr_list += [psnr.to(data.device)]
                msssim_list += [msssim.to(data.device)]
                if model.training:
                    bpp_res_est_list += [bpp_res_est.to(data.device)]
                x_hat_list.append(x_prev)
            x_hat = torch.cat(x_hat_list,dim=0)
        elif model.name in ['DVC-pretrained']:
            B,_,H,W = data.size()
            x_prev = data[0:1]
            x_hat_list = []
            for i in range(1,B):
                x_prev, mseloss, warploss, interloss, bpp_feature, bpp_z, bpp_mv, bpp = \
                    model(data[i:i+1],x_prev)
                x_prev = x_prev.detach()
                img_loss_list += [2048*mseloss.to(data.device)]
                aux_loss_list += [10.0*torch.log(1/warploss)/torch.log(torch.FloatTensor([10])).squeeze(0).to(data.device)]
                bpp_est_list += [bpp.to(data.device)]
                bpp_act_list += [bpp.to(data.device)]
                psnr_list += [10.0*torch.log(1/mseloss)/torch.log(torch.FloatTensor([10])).squeeze(0).to(data.device)]
                msssim_list += [10.0*torch.log(1/interloss)/torch.log(torch.FloatTensor([10])).squeeze(0).to(data.device)]
                x_hat_list.append(x_prev)
            x_hat = torch.cat(x_hat_list,dim=0)
        elif 'LSVC' in model.name:
            B,_,H,W = data.size()
            x_hat, x_mc, x_wp, rec_loss, warp_loss, mc_loss, bpp_res, bpp = model(data.detach())
            if model.stage == 'MC':
                img_loss = mc_loss*model.r
            elif model.stage == 'REC':
                img_loss = rec_loss*model.r
            elif model.stage == 'WP':
                img_loss = warp_loss*model.r
            else:
                print('unknown stage')
                exit(1)
            img_loss_list = [img_loss]
            N = B-1
            psnr_list += PSNR(data[1:], x_hat, use_list=True)
            msssim_list += PSNR(data[1:], x_mc, use_list=True)
            aux_loss_list += PSNR(data[1:], x_wp, use_list=True)
            for pos in range(N):
                bpp_est_list += [(bpp).to(data.device)]
                if model.training:
                    bpp_res_est_list += [(bpp_res).to(data.device)]
                bpp_act_list += [(bpp).to(data.device)]
                # aux_loss_list += [10.0*torch.log(1/warp_loss)/torch.log(torch.FloatTensor([10])).squeeze(0).to(data.device)]
                # msssim_list += [10.0*torch.log(1/mc_loss)/torch.log(torch.FloatTensor([10])).squeeze(0).to(data.device)]

    if model.training:
        return x_hat,img_loss_list,bpp_est_list,bpp_res_est_list,aux_loss_list,psnr_list,msssim_list,bpp_act_list
    else:
        return x_hat,img_loss_list,bpp_est_list,aux_loss_list,psnr_list,msssim_list,bpp_act_list
    
def write_image(x, prefix):
    for j in range(x.size(0)):
        img = transforms.ToPILImage()(x[j])
        img.save(prefix + str(j) + '.jpg')
            
def index2GOP(i, clip_len, fP = 6, bP = 6):
    # bi: fP=bP=6
    # uni:fP=12,bp=0
    # input: 
    # - idx: the frame index of interest
    # output: 
    # - ranges: the range(s) of GOP involving this frame
    # - max_seen: max index has been seen
    # - max_proc: max processed index
    # normally progressive coding will get 1 or 2 range(s)
    # parallel coding will get 1 range
    
    GOP = fP + bP + 1
    # 0 1  2  3  4  5  6  7  8  9  10 11 12 13
    # I fP fP fP fP fP fP bP bP bP bP bP bP I 
    ranges = []
    # <      case 1    >  
    # first time calling this function will mostly fall in case 1
    # case 1 will create one range
    if i%GOP <= fP:
        # e.g.: i=4,left=0,right=6,mid=0
        mid = i
        left = i
        right = min(i//GOP*GOP+fP,clip_len-1)
        _range = [j for j in range(mid,right+1)]
        ranges += [_range]
    #                     <      case 2   >
    # later calling this function will fall in case 2
    # case 2 will create one range if parallel or two ranges if progressive
    else:
        # e.g.: i=8,left=7,right=19,mid=13
        mid = min((i//GOP+1)*GOP,clip_len-1)
        left = i
        right = min((i//GOP+1)*GOP+fP,clip_len-1)
        possible_I = (i//GOP+1)*GOP
        # first backward
        _range = [j for j in range(mid,left-1,-1)]
        ranges += [_range]
        # then forward
        if right >= mid+1:
            _range = [j for j in range(mid+1,right+1)]
            ranges += [_range]
    max_seen, max_proc = i, right
    return ranges, max_seen, max_proc
        
class StandardVideoCodecs(nn.Module):
    def __init__(self, name):
        super(StandardVideoCodecs, self).__init__()
        self.name = name # x264, x265?
        self.placeholder = torch.nn.Parameter(torch.zeros(1))
        init_training_params(self)
    
    def loss(self, pix_loss, bpp_loss, aux_loss, app_loss=None):
        if app_loss is None:
            return self.r_img*pix_loss + self.r_bpp*bpp_loss + self.r_aux*aux_loss
        else:
            return self.r_app*app_loss + self.r_img*pix_loss + self.r_bpp*bpp_loss + self.r_aux*aux_loss
        
def I_compression(Y1_raw, I_level, model_name=''):
    # we can compress with bpg,deepcod ...
    batch_size, _, Height, Width = Y1_raw.shape
    prename = "tmp/frames/prebpg" + model_name
    binname = "tmp/frames/bpg" + model_name
    postname = "tmp/frames/postbpg" + model_name
    raw_img = transforms.ToPILImage()(Y1_raw.squeeze(0))
    raw_img.save(prename + '.jpg')
    pre_bits = os.path.getsize(prename + '.jpg')*8
    os.system('bpgenc -f 444 -m 9 ' + prename + '.jpg -o ' + binname + '.bin -q ' + str(I_level))
    os.system('bpgdec ' + binname + '.bin -o ' + postname + '.jpg')
    post_bits = os.path.getsize(binname + '.bin')*8/(Height * Width * batch_size)
    bpp_act = torch.FloatTensor([post_bits]).squeeze(0)
    bpg_img = Image.open(postname + '.jpg').convert('RGB')
    Y1_com = transforms.ToTensor()(bpg_img).unsqueeze(0)
    psnr = PSNR(Y1_raw, Y1_com)
    msssim = MSSSIM(Y1_raw, Y1_com)
    bpp_est = bpp_act
    loss = aux_loss = torch.FloatTensor([0]).squeeze(0)
    return Y1_com, bpp_est, loss, aux_loss, bpp_act, psnr, msssim
    
def load_state_dict_only(model, state_dict, keyword):
    own_state = model.state_dict()
    for name, param in state_dict.items():
        if keyword not in name: continue
        if name in own_state:
            own_state[name].copy_(param)
    
def load_state_dict_whatever(model, state_dict):
    own_state = model.state_dict()
    for name, param in state_dict.items():
        if name.endswith("._offset") or name.endswith("._quantized_cdf") or name.endswith("._cdf_length") or name.endswith(".scale_table"):
             continue
        if name in own_state and own_state[name].size() == param.size():
            own_state[name].copy_(param)
            
def load_state_dict_all(model, state_dict):
    own_state = model.state_dict()
    for name, param in state_dict.items():
        if name.endswith("._offset") or name.endswith("._quantized_cdf") or name.endswith("._cdf_length") or name.endswith(".scale_table"):
             continue
        own_state[name].copy_(param)
    
def PSNR(Y1_raw, Y1_com, use_list=False):
    Y1_com = Y1_com.to(Y1_raw.device)
    log10 = torch.log(torch.FloatTensor([10])).squeeze(0).to(Y1_raw.device)
    if not use_list:
        train_mse = torch.mean(torch.pow(Y1_raw - Y1_com, 2))
        quality = 10.0*torch.log(1/train_mse)/log10
    else:
        b = Y1_raw.size()[0]
        quality = []
        for i in range(b):
            train_mse = torch.mean(torch.pow(Y1_raw[i:i+1] - Y1_com[i:i+1].unsqueeze(0), 2))
            psnr = 10.0*torch.log(1/train_mse)/log10
            quality.append(psnr)
    return quality

def MSSSIM(Y1_raw, Y1_com, use_list=False):
    Y1_com = Y1_com.to(Y1_raw.device)
    if not use_list:
        quality = pytorch_msssim.ms_ssim(Y1_raw, Y1_com)
    else:
        bs = Y1_raw.size()[0]
        quality = []
        for i in range(bs):
            quality.append(pytorch_msssim.ms_ssim(Y1_raw[i].unsqueeze(0), Y1_com[i].unsqueeze(0)))
    return quality
    
def calc_loss(Y1_raw, Y1_com, r, use_psnr):
    if use_psnr:
        loss = torch.mean(torch.pow(Y1_raw - Y1_com.to(Y1_raw.device), 2))*r
    else:
        metrics = MSSSIM(Y1_raw, Y1_com.to(Y1_raw.device))
        loss = r*(1-metrics)
    return loss

class ConvLSTM(nn.Module):
    def __init__(self, channels=128, forget_bias=1.0, activation=F.relu):
        super(ConvLSTM, self).__init__()
        self.conv = nn.Conv2d(2*channels, 4*channels, kernel_size=3, stride=1, padding=1)
        self._forget_bias = forget_bias
        self._activation = activation
        self._channels = channels

    def forward(self, x, state):
        c, h = torch.split(state,self._channels,dim=1)
        x = torch.cat((x, h), dim=1)
        y = self.conv(x)
        j, i, f, o = torch.split(y, self._channels, dim=1)
        f = torch.sigmoid(f + self._forget_bias)
        i = torch.sigmoid(i)
        c = c * f + i * self._activation(j)
        o = torch.sigmoid(o)
        h = o * self._activation(c)

        return h, torch.cat((c, h),dim=1)

def set_model_grad(model,requires_grad=True):
    for k,v in model.named_parameters():
        v.requires_grad = requires_grad
    
def get_actual_bits(self, string):
    bits_act = torch.FloatTensor([len(b''.join(string))*8]).squeeze(0)
    return bits_act
        
def get_estimate_bits(self, likelihoods):
    # log2 = torch.log(torch.FloatTensor([2])).squeeze(0).to(likelihoods.device)
    # bits_est = torch.sum(torch.log(likelihoods)) / (-log2)
    bits_est = torch.sum(torch.clamp(-1.0 * torch.log(likelihoods + 1e-5) / math.log(2.0), 0, 50))
    return bits_est

class Coder2D(nn.Module):
    def __init__(self, keyword, in_channels=2, channels=128, kernel=3, padding=1, 
                noMeasure=True, downsample=True, entropy_trick=True):
        super(Coder2D, self).__init__()
        if downsample:
            self.enc_conv1 = nn.Conv2d(in_channels, channels, kernel_size=kernel, stride=2, padding=padding)
            self.enc_conv2 = nn.Conv2d(channels, channels, kernel_size=kernel, stride=2, padding=padding)
            self.enc_conv3 = nn.Conv2d(channels, channels, kernel_size=kernel, stride=2, padding=padding)
            self.enc_conv4 = nn.Conv2d(channels, channels, kernel_size=kernel, stride=2, padding=padding, bias=False)
            self.gdn1 = GDN(channels)
            self.gdn2 = GDN(channels)
            self.gdn3 = GDN(channels)
            self.dec_conv1 = nn.ConvTranspose2d(channels, channels, kernel_size=kernel, stride=2, padding=padding, output_padding=1)
            self.dec_conv2 = nn.ConvTranspose2d(channels, channels, kernel_size=kernel, stride=2, padding=padding, output_padding=1)
            self.dec_conv3 = nn.ConvTranspose2d(channels, channels, kernel_size=kernel, stride=2, padding=padding, output_padding=1)
            self.dec_conv4 = nn.ConvTranspose2d(channels, in_channels, kernel_size=kernel, stride=2, padding=padding, output_padding=1)
            self.igdn1 = GDN(channels, inverse=True)
            self.igdn2 = GDN(channels, inverse=True)
            self.igdn3 = GDN(channels, inverse=True)
        if keyword in ['MLVC','RLVC','rpm']:
            # for recurrent sequential model
            self.entropy_bottleneck = RecProbModel(channels)
            self.conv_type = 'rec'
            self.entropy_type = 'rpm'
        elif keyword in ['attn']:
            # for batch model
            self.entropy_bottleneck = MeanScaleHyperPriors(channels,entropy_trick=entropy_trick)
            self.conv_type = 'attn'
            self.entropy_type = 'mshp'
        elif keyword in ['mshp']:
            # for image codec, single frame
            self.entropy_bottleneck = MeanScaleHyperPriors(channels,entropy_trick=entropy_trick)
            self.conv_type = 'non-rec' # not need for single image compression
            self.entropy_type = 'mshp'
        elif keyword in ['DVC','base','DCVC','DCVC_v2']:
            # for sequential model with no recurrent network
            from compressai.entropy_models import EntropyBottleneck
            EntropyBottleneck.get_actual_bits = get_actual_bits
            EntropyBottleneck.get_estimate_bits = get_estimate_bits
            self.entropy_bottleneck = EntropyBottleneck(channels)
            self.conv_type = 'non-rec'
            self.entropy_type = 'base'
        elif keyword == 'RLVC2':
            self.conv_type = 'rec'
            self.entropy_type = 'rpm2'
            self.RPM = RPM(channels)
            BitEstimator.get_actual_bits = get_actual_bits
            BitEstimator.get_estimate_bits = get_estimate_bits
            self.entropy_bottleneck = BitEstimator(channels)
        else:
            print('Bottleneck not implemented for:',keyword)
            exit(1)
        # print('Conv type:',self.conv_type,'entropy type:',self.entropy_type)
        self.channels = channels
        if self.conv_type == 'rec':
            self.enc_lstm = ConvLSTM(channels)
            self.dec_lstm = ConvLSTM(channels)
        elif self.conv_type == 'attn':
            from DVC.subnet import FeedForward,Attention,PreNorm,RotaryEmbedding,AxialRotaryEmbedding
            self.layers = nn.ModuleList([])
            depth = 12
            for _ in range(depth):
                ff = FeedForward(channels)
                s_attn = Attention(channels, dim_head = 64, heads = 8)
                t_attn = Attention(channels, dim_head = 64, heads = 8)
                t_attn, s_attn, ff = map(lambda t: PreNorm(channels, t), (t_attn, s_attn, ff))
                self.layers.append(nn.ModuleList([t_attn, s_attn, ff]))
            self.frame_rot_emb = RotaryEmbedding(64)
            self.image_rot_emb = AxialRotaryEmbedding(64)
            
        self.downsample = downsample
        self.updated = False
        self.noMeasure = noMeasure
        # include two average meter to measure time
        
    def compress(self, x, rae_hidden=None, rpm_hidden=None, RPM_flag=False, prior=None, decodeLatent=False, prior_latent=None):
        # update only once during testing
        if not self.updated and not self.training:
            self.entropy_bottleneck.update(force=True)
            self.updated = True
            
        # record network time and arithmetic coding time
        self.net_t = 0
        self.AC_t = 0
        
        t_0 = time.perf_counter()
            
        # latent states
        if self.conv_type == 'rec':
            state_enc, state_dec = torch.split(rae_hidden.to(x.device),self.channels*2,dim=1)
            
        # compress
        if self.downsample:
            x = self.gdn1(self.enc_conv1(x))
            x = self.gdn2(self.enc_conv2(x))
            
            if self.conv_type == 'rec':
                x, state_enc = self.enc_lstm(x, state_enc)
                
            x = self.gdn3(self.enc_conv3(x))
            x = self.enc_conv4(x) # latent optical flow
            
            if self.conv_type == 'attn':
                B,C,H,W = x.size()
                frame_pos_emb = self.frame_rot_emb(B,device=x.device)
                image_pos_emb = self.image_rot_emb(H,W,device=x.device)
                x = x.permute(0,2,3,1).reshape(1,-1,C).contiguous()
                for (t_attn, s_attn, ff) in self.layers:
                    x = t_attn(x, 'b (f n) d', '(b n) f d', n = H*W, rot_emb = frame_pos_emb) + x
                    x = s_attn(x, 'b (f n) d', '(b f) n d', f = B, rot_emb = image_pos_emb) + x
                    x = ff(x) + x
                x = x.view(B,H,W,C).permute(0,3,1,2).contiguous()
                
            latent = x
        else:
            latent = x
        
        self.net_t += time.perf_counter() - t_0
            
        # quantization + entropy coding
        if self.entropy_type == 'base':
            # encoding
            t_0 = time.perf_counter()
            latent_string = self.entropy_bottleneck.compress(latent)
            if decodeLatent:
                latent_hat, _ = self.entropy_bottleneck(latent, training=self.training)
            self.entropy_bottleneck.eNet_t = 0
            self.entropy_bottleneck.eAC_t = time.perf_counter() - t_0
            latentSize = latent.size()[-2:]
        elif self.entropy_type == 'mshp':
            latent_hat, latent_string, latentSize = self.entropy_bottleneck.compress_slow(latent,decode=decodeLatent)
        else:
            self.entropy_bottleneck.set_RPM(RPM_flag)
            latent_hat, latent_string, rpm_hidden, prior_latent = self.entropy_bottleneck.compress_slow(latent,rpm_hidden,prior_latent)
            latentSize = latent.size()[-2:]
            
        self.net_t += self.entropy_bottleneck.eNet_t
        self.AC_t += self.entropy_bottleneck.eAC_t
        # if decodeLatent and self.entropy_type != 'rpm':
        #     self.net_t += self.entropy_bottleneck.dnet_t
        #     self.AC_t += self.entropy_bottleneck.dAC_t
            
        if decodeLatent:
            t_0 = time.perf_counter()
            # decompress
            if self.downsample:
                x = latent_hat
                x = self.igdn1(self.dec_conv1(x))
                x = self.igdn2(self.dec_conv2(x))
                
                if self.conv_type == 'rec':
                    x, state_dec = self.enc_lstm(x, state_dec)
                    
                x = self.igdn3(self.dec_conv3(x))
                hat = self.dec_conv4(x)
            else:
                hat = latent_hat
            self.net_t += time.perf_counter() - t_0
            
        if self.conv_type == 'rec':
            rae_hidden = torch.cat((state_enc, state_dec),dim=1)
            if rae_hidden is not None:
                rae_hidden = rae_hidden.detach()
                
        # actual bits
        bits_act = self.entropy_bottleneck.get_actual_bits(latent_string)
        
        if decodeLatent:
            return hat,latent_string, rae_hidden, rpm_hidden, bits_act, latentSize, prior_latent
        else:
            return latent_string, rae_hidden, rpm_hidden, bits_act, latentSize, prior_latent
        
    def decompress(self, latent_string, rae_hidden=None, rpm_hidden=None, RPM_flag=False, prior=None, latentSize=None, prior_latent=None):
        # update only once during testing
        if not self.updated and not self.training:
            self.entropy_bottleneck.update(force=True)
            self.updated = True
            
        self.net_t = 0
        self.AC_t = 0
            
        if self.entropy_type == 'base':
            t_0 = time.perf_counter()
            latent_hat = self.entropy_bottleneck.decompress(latent_string, latentSize)
            self.entropy_bottleneck.dnet_t = 0
            self.entropy_bottleneck.dAC_t = time.perf_counter() - t_0
        elif self.entropy_type == 'mshp':
            latent_hat = self.entropy_bottleneck.decompress_slow(latent_string, latentSize)
        else:
            self.entropy_bottleneck.set_RPM(RPM_flag)
            latent_hat, rpm_hidden, prior_latent = self.entropy_bottleneck.decompress_slow(latent_string, latentSize, rpm_hidden, prior_latent)
            
        self.net_t += self.entropy_bottleneck.dnet_t
        self.AC_t += self.entropy_bottleneck.dAC_t
            
        # latent states
        if self.conv_type == 'rec':
            state_enc, state_dec = torch.split(rae_hidden.to(latent_hat.device),self.channels*2,dim=1)
        
        t_0 = time.perf_counter()
        # decompress
        if self.downsample:
            x = latent_hat
            x = self.igdn1(self.dec_conv1(x))
            x = self.igdn2(self.dec_conv2(x))
            
            if self.conv_type == 'rec':
                x, state_dec = self.enc_lstm(x, state_dec)
                
            x = self.igdn3(self.dec_conv3(x))
            hat = self.dec_conv4(x)
        else:
            hat = latent_hat
        self.net_t += time.perf_counter() - t_0
        
        if self.conv_type == 'rec':
            rae_hidden = torch.cat((state_enc, state_dec),dim=1)
            if rae_hidden is not None:
                rae_hidden = rae_hidden.detach()
            
        return hat, rae_hidden, rpm_hidden, prior_latent
        
    def forward(self, x, rae_hidden=None, rpm_hidden=None, RPM_flag=False, prior=None, prior_latent=None):
        # Time measurement: start
        if not self.noMeasure:
            t_0 = time.perf_counter()
            
        self.realCom = not self.training
        # update only once during testing
        if not self.updated and self.realCom and self.entropy_type != 'rpm2':
            self.entropy_bottleneck.update(force=True)
            self.updated = True
            
        if not self.noMeasure:
            self.enc_t = self.dec_t = 0
        
        # latent states
        if self.conv_type == 'rec':
            state_enc, state_dec = torch.split(rae_hidden.to(x.device),self.channels*2,dim=1) 
            
        # compress
        if self.downsample:
            x = self.gdn1(self.enc_conv1(x))
            x = self.gdn2(self.enc_conv2(x))
            
            if self.conv_type == 'rec':
                x, state_enc = self.enc_lstm(x, state_enc)
            elif self.conv_type == 'attn':
                pass
                
            x = self.gdn3(self.enc_conv3(x))
            x = self.enc_conv4(x) # latent optical flow
            
            if self.conv_type == 'attn':
                B,C,H,W = x.size()
                frame_pos_emb = self.frame_rot_emb(B,device=x.device)
                image_pos_emb = self.image_rot_emb(H,W,device=x.device)
                x = x.permute(0,2,3,1).reshape(1,-1,C).contiguous()
                for (t_attn, s_attn, ff) in self.layers:
                    x = t_attn(x, 'b (f n) d', '(b n) f d', n = H*W, rot_emb = frame_pos_emb) + x
                    x = s_attn(x, 'b (f n) d', '(b f) n d', f = B, rot_emb = image_pos_emb) + x
                    x = ff(x) + x
                x = x.view(B,H,W,C).permute(0,3,1,2).contiguous()
                
            latent = x
        else:
            latent = x
        
        # Time measurement: end
        if not self.noMeasure:
            self.enc_t += time.perf_counter() - t_0
        
        # quantization + entropy coding
        if self.entropy_type == 'base':
            if self.noMeasure:
                latent_hat, likelihoods = self.entropy_bottleneck(latent, training=self.training)
                if self.realCom:
                    latent_string = self.entropy_bottleneck.compress(latent)
            else:
                # encoding
                t_0 = time.perf_counter()
                latent_string = self.entropy_bottleneck.compress(latent)
                self.entropy_bottleneck.enc_t = time.perf_counter() - t_0
                # decoding
                t_0 = time.perf_counter()
                latent_hat = self.entropy_bottleneck.decompress(latent_string, latent.size()[-2:])
                self.entropy_bottleneck.dec_t = time.perf_counter() - t_0
        elif self.entropy_type == 'mshp':
            if self.noMeasure:
                latent_hat, likelihoods = self.entropy_bottleneck(latent, training=self.training)
                if self.realCom:
                    latent_string = self.entropy_bottleneck.compress(latent)
            else:
                _,latent_string, shape = self.entropy_bottleneck.compress_slow(latent, decode=True)
                latent_hat = self.entropy_bottleneck.decompress_slow(latent_string, shape)
        elif self.entropy_type == 'rpm2':
            if self.training:
                half = float(0.5)
                noise = torch.empty_like(latent).uniform_(-half, half)
                latent_hat = latent + noise
            else:
                latent_hat = torch.round(latent)
            if RPM_flag:
                assert prior_latent is not None, 'prior latent is none!'
                sigma, mu, rpm_hidden = self.RPM(prior_latent, rpm_hidden)
                mu = torch.zeros_like(sigma)
                sigma = sigma.clamp(1e-5, 1e10)
                gaussian = torch.distributions.laplace.Laplace(mu, sigma)
                likelihoods = gaussian.cdf(latent_hat + 0.5) - gaussian.cdf(latent_hat - 0.5)
            else:
                likelihoods = self.entropy_bottleneck(latent_hat + 0.5) - self.entropy_bottleneck(latent_hat - 0.5)
            prior_latent = torch.round(latent).detach()
        else:
            self.entropy_bottleneck.set_RPM(RPM_flag)
            if self.noMeasure:
                latent_hat, likelihoods, rpm_hidden, prior_latent = self.entropy_bottleneck(latent, rpm_hidden, training=self.training, prior_latent=prior_latent)
                if self.realCom:
                    latent_string = self.entropy_bottleneck.compress(latent)
            else:
                _, latent_string, _, _ = self.entropy_bottleneck.compress_slow(latent,rpm_hidden,prior_latent=prior_latent)
                latent_hat, rpm_hidden, prior_latent = self.entropy_bottleneck.decompress_slow(latent_string, latent.size()[-2:], rpm_hidden, prior_latent=prior_latent)
            
        # add in the time in entropy bottleneck
        if not self.noMeasure:
            self.enc_t += self.entropy_bottleneck.enc_t
            self.dec_t += self.entropy_bottleneck.dec_t
        
        # calculate bpp (estimated) if it is training else it will be set to 0
        if self.noMeasure:
            bits_est = self.entropy_bottleneck.get_estimate_bits(likelihoods)
        else:
            bits_est = torch.zeros(latent_hat.size(0)).squeeze(0).to(x.device)
        
        # calculate bpp (actual)
        if self.realCom and self.entropy_type != 'rpm2':
            bits_act = self.entropy_bottleneck.get_actual_bits(latent_string)
        else:
            bits_act = bits_est

        # Time measurement: start
        if not self.noMeasure:
            t_0 = time.perf_counter()
            
        # decompress
        if self.downsample:
            x = latent_hat
            x = self.igdn1(self.dec_conv1(x))
            x = self.igdn2(self.dec_conv2(x))
            
            if self.conv_type == 'rec':
                x, state_dec = self.enc_lstm(x, state_dec)
                
            x = self.igdn3(self.dec_conv3(x))
            hat = self.dec_conv4(x)
        else:
            hat = latent_hat
        
        if self.conv_type == 'rec':
            rae_hidden = torch.cat((state_enc, state_dec),dim=1)
            if rae_hidden is not None:
                rae_hidden = rae_hidden.detach()
        
        # Time measurement: end
        if not self.noMeasure:
            self.enc_t += time.perf_counter() - t_0
            self.dec_t += time.perf_counter() - t_0
        
        # auxilary loss
        aux_loss = self.entropy_bottleneck.loss() if self.entropy_type != 'rpm2' else torch.FloatTensor([0]).to(hat.device)
            
        return hat, rae_hidden, rpm_hidden, bits_act, bits_est, aux_loss, prior_latent
            
    def compress_sequence(self,x):
        bs,c,h,w = x.size()
        x_est = torch.FloatTensor([0 for _ in x]).cuda()
        x_act = torch.FloatTensor([0 for _ in x]).cuda()
        x_aux = torch.FloatTensor([0]).cuda()
        if not self.downsample:
            rpm_hidden = torch.zeros(1,self.channels*2,h,w)
        else:
            rpm_hidden = torch.zeros(1,self.channels*2,h//16,w//16)
        rae_hidden = torch.zeros(1,self.channels*4,h//4,w//4)
        prior_latent = None
        if not self.noMeasure:
            enc_t = dec_t = 0
        x_hat_list = []
        for frame_idx in range(bs): 
            x_i = x[frame_idx,:,:,:].unsqueeze(0)
            x_hat_i,rae_hidden,rpm_hidden,x_act_i,x_est_i,x_aux_i,prior_latent = self.forward(x_i, rae_hidden, rpm_hidden, frame_idx>=1,prior_latent=prior_latent)
            x_hat_list.append(x_hat_i.squeeze(0))
            
            # calculate bpp (estimated) if it is training else it will be set to 0
            x_est[frame_idx] += x_est_i.cuda()
            
            # calculate bpp (actual)
            x_act[frame_idx] += x_act_i.cuda()
            
            # aux
            x_aux += x_aux_i.cuda()
            
            if not self.noMeasure:
                enc_t += self.enc_t
                dec_t += self.dec_t
        x_hat = torch.stack(x_hat_list, dim=0)
        if not self.noMeasure:
            self.enc_t,self.dec_t = enc_t,dec_t
        return x_hat,x_act,x_est,x_aux/bs
    
def generate_graph(graph_type='default'):
    # 7 nodes, 6 edges
    # the order to iterate graph also matters, leave it now
    # BFS or DFS?
    if graph_type == 'default':
        g = {}
        for k in range(14):
            g[k] = [k+1]
        layers = [[i+1] for i in range(14)] # elements in layers
        parents = {i+1:i for i in range(14)}
    elif graph_type == 'onehop':    
        g = {0:[i+1 for i in range(14)]}
        layers = [[i+1 for i in range(14)]]
        parents = {i+1:0 for i in range(14)}
    elif graph_type == '2layers':
        g = {0:[1,2]}
        layers = [[1,2]] # elements in layers
        parents = {1:0,2:0}
    elif graph_type == '3layers':
        g = {0:[1,4],1:[2,3],4:[5,6]}
        layers = [[1,4],[2,3,5,6]] # elements in layers
        parents = {1:0,4:0,2:1,3:1,5:4,6:4}
    elif graph_type == '4layers':
        # 0
        # 1       8
        # 2   5   9     12
        # 3 4 6 7 10 11 13 14
        g = {0:[1,8],1:[2,5],8:[9,12],2:[3,4],5:[6,7],9:[10,11],12:[13,14]}
        layers = [[1,8],[2,5,9,12],[3,4,6,7,10,11,13,14]] # elements in layers
        parents = {1:0,8:0,2:1,5:1,9:8,12:8,3:2,4:2,6:5,7:5,10:9,11:9,13:12,14:12}
    elif graph_type == '5layers':
        # 0
        # 1                   16
        # 2       9           17          24
        # 3   6   10    13    18    21    25    28
        # 4 5 7 8 11 12 14 15 19 20 22 23 26 27 29 30
        g = {0:[1,16],1:[2,9],16:[17,24],2:[3,6],9:[10,13],17:[18,21],24:[25,28],
            3:[4,5],6:[7,8],10:[11,12],13:[14,15],18:[19,20],21:[22,23],25:[26,27],28:[29,30]}
        layers = [[1,16],[2,9,17,24],[3,6,10,13,18,21,25,28],
                [4,5,7,8,11,12,14,15,19,20,22,23,26,27,29,30]]
        parents = {1:0,16:0,2:1,9:1,17:16,24:16,3:2,6:2,10:9,13:9,18:17,21:17,25:24,28:24,
                4:3,5:3,7:6,8:6,11:10,12:10,14:13,15:13,19:18,20:18,22:21,23:21,26:25,27:25,29:28,30:28}
    else:
        print('Undefined graph type:',graph_type)
        exit(1)
    return g,layers,parents

modelspath = 'DVC/flow_pretrain_np/'
Backward_tensorGrid = {}

def torch_warp(tensorInput, tensorFlow):
    device_id = tensorInput.device.index
    if str(tensorFlow.size()) not in Backward_tensorGrid:
            tensorHorizontal = torch.linspace(-1.0, 1.0, tensorFlow.size(3)).view(1, 1, 1, tensorFlow.size(3)).expand(tensorFlow.size(0), -1, tensorFlow.size(2), -1)
            tensorVertical = torch.linspace(-1.0, 1.0, tensorFlow.size(2)).view(1, 1, tensorFlow.size(2), 1).expand(tensorFlow.size(0), -1, -1, tensorFlow.size(3))
            Backward_tensorGrid[str(tensorFlow.size())] = torch.cat([ tensorHorizontal, tensorVertical ], 1).to(device_id)

    tensorFlow = torch.cat([tensorFlow[:, 0:1, :, :] / ((tensorInput.size(3) - 1.0) / 2.0), tensorFlow[:, 1:2, :, :] / ((tensorInput.size(2) - 1.0) / 2.0) ], 1)

    return torch.nn.functional.grid_sample(input=tensorInput, grid=(Backward_tensorGrid[str(tensorFlow.size())] + tensorFlow).permute(0, 2, 3, 1), mode='bilinear', padding_mode='border')

def log10(x):
    numerator = torch.log(x)
    denominator = torch.log(10)
    return numerator / denominator


def flow_warp(im, flow):
    warp = torch_warp(im, flow)

    return warp


def loadweightformnp(layername):
    index = layername.find('modelL')
    if index == -1:
        print('laod models error!!')
    else:
        name = layername[index:index + 11]
        modelweight = modelspath + name + '-weight.npy'
        modelbias = modelspath + name + '-bias.npy'
        weightnp = np.load(modelweight)
        # weightnp = np.transpose(weightnp, [2, 3, 1, 0])
        # print(weightnp)
        biasnp = np.load(modelbias)

        # init_weight = lambda shape, dtype: weightnp
        # init_bias   = lambda shape, dtype: biasnp
        # print('Done!')

        return torch.from_numpy(weightnp), torch.from_numpy(biasnp)
        # return init_weight, init_bias

class MEBasic(nn.Module):
    '''
    Get flow
    '''
    def __init__(self, layername):
        super(MEBasic, self).__init__()
        self.conv1 = nn.Conv2d(8, 32, 7, 1, padding=3)
        self.conv1.weight.data, self.conv1.bias.data = loadweightformnp(layername + '_F-1')
        self.relu1 = nn.ReLU()
        self.conv2 = nn.Conv2d(32, 64, 7, 1, padding=3)
        self.conv2.weight.data, self.conv2.bias.data = loadweightformnp(layername + '_F-2')
        self.relu2 = nn.ReLU()
        self.conv3 = nn.Conv2d(64, 32, 7, 1, padding=3)
        self.conv3.weight.data, self.conv3.bias.data = loadweightformnp(layername + '_F-3')
        self.relu3 = nn.ReLU()
        self.conv4 = nn.Conv2d(32, 16, 7, 1, padding=3)
        self.conv4.weight.data, self.conv4.bias.data = loadweightformnp(layername + '_F-4')
        self.relu4 = nn.ReLU()
        self.conv5 = nn.Conv2d(16, 2, 7, 1, padding=3)
        self.conv5.weight.data, self.conv5.bias.data = loadweightformnp(layername + '_F-5')

    def forward(self, x):
        x = self.relu1(self.conv1(x))
        x = self.relu2(self.conv2(x))
        x = self.relu3(self.conv3(x))
        x = self.relu4(self.conv4(x))
        x = self.conv5(x)
        return x


def bilinearupsacling(inputfeature):
    inputheight = inputfeature.size()[2]
    inputwidth = inputfeature.size()[3]
    # print(inputfeature.size())
    outfeature = F.interpolate(inputfeature, (inputheight * 2, inputwidth * 2), mode='bilinear')
    # print(outfeature.size())
    return outfeature
def bilinearupsacling2(inputfeature):
    inputheight = inputfeature.size()[2]
    inputwidth = inputfeature.size()[3]
    outfeature = F.interpolate(inputfeature, (inputheight * 2, inputwidth * 2), mode='bilinear', align_corners=True)
    return outfeature


class ResBlock(nn.Module):
    def __init__(self, inputchannel, outputchannel, kernel_size, stride=1):
        super(ResBlock, self).__init__()
        self.relu1 = nn.ReLU()
        self.conv1 = nn.Conv2d(inputchannel, outputchannel, kernel_size, stride, padding=kernel_size//2)
        torch.nn.init.xavier_uniform_(self.conv1.weight.data)
        torch.nn.init.constant_(self.conv1.bias.data, 0.0)
        self.relu2 = nn.ReLU()
        self.conv2 = nn.Conv2d(outputchannel, outputchannel, kernel_size, stride, padding=kernel_size//2)
        torch.nn.init.xavier_uniform_(self.conv2.weight.data)
        torch.nn.init.constant_(self.conv2.bias.data, 0.0)
        if inputchannel != outputchannel:
            self.adapt_conv = nn.Conv2d(inputchannel, outputchannel, 1)
            torch.nn.init.xavier_uniform_(self.adapt_conv.weight.data)
            torch.nn.init.constant_(self.adapt_conv.bias.data, 0.0)
        else:
            self.adapt_conv = None

    def forward(self, x):
        x_1 = self.relu1(x)
        firstlayer = self.conv1(x_1)
        firstlayer = self.relu2(firstlayer)
        seclayer = self.conv2(firstlayer)
        if self.adapt_conv is None:
            return x + seclayer
        else:
            return self.adapt_conv(x) + seclayer

class Warp_net(nn.Module):
    def __init__(self, in_channels=6,out_channels=3):
        super(Warp_net, self).__init__()
        channelnum = 64

        self.feature_ext = nn.Conv2d(in_channels, channelnum, 3, padding=1)# feature_ext
        self.f_relu = nn.ReLU()
        torch.nn.init.xavier_uniform_(self.feature_ext.weight.data)
        torch.nn.init.constant_(self.feature_ext.bias.data, 0.0)
        self.conv0 = ResBlock(channelnum, channelnum, 3)#c0
        self.conv0_p = nn.AvgPool2d(2, 2)# c0p
        self.conv1 = ResBlock(channelnum, channelnum, 3)#c1
        self.conv1_p = nn.AvgPool2d(2, 2)# c1p
        self.conv2 = ResBlock(channelnum, channelnum, 3)# c2
        self.conv3 = ResBlock(channelnum, channelnum, 3)# c3
        self.conv4 = ResBlock(channelnum, channelnum, 3)# c4
        self.conv5 = ResBlock(channelnum, channelnum, 3)# c5
        self.conv6 = nn.Conv2d(channelnum, out_channels, 3, padding=1)
        torch.nn.init.xavier_uniform_(self.conv6.weight.data)
        torch.nn.init.constant_(self.conv6.bias.data, 0.0)

    def forward(self, x):
        feature_ext = self.f_relu(self.feature_ext(x))
        c0 = self.conv0(feature_ext)
        c0_p = self.conv0_p(c0)
        c1 = self.conv1(c0_p)
        c1_p = self.conv1_p(c1)
        c2 = self.conv2(c1_p)
        c3 = self.conv3(c2)
        c3_u = c1 + bilinearupsacling2(c3)#torch.nn.functional.interpolate(input=c3, scale_factor=2, mode='bilinear', align_corners=True)
        c4 = self.conv4(c3_u)
        c4_u = c0 + bilinearupsacling2(c4)# torch.nn.functional.interpolate(input=c4, scale_factor=2, mode='bilinear', align_corners=True)
        c5 = self.conv5(c4_u)
        c5 = self.conv6(c5)
        return c5

class ME_Spynet(nn.Module):
    '''
    Get flow
    '''
    def __init__(self, layername='motion_estimation'):
        super(ME_Spynet, self).__init__()
        self.L = 4
        self.moduleBasic = torch.nn.ModuleList([ MEBasic(layername + 'modelL' + str(intLevel + 1)) for intLevel in range(4) ])
        
    def forward(self, im1, im2):
        batchsize = im1.size()[0]
        im1_pre = im1
        im2_pre = im2

        im1list = [im1_pre]
        im2list = [im2_pre]
        for intLevel in range(self.L - 1):
            im1list.append(F.avg_pool2d(im1list[intLevel], kernel_size=2, stride=2))# , count_include_pad=False))
            im2list.append(F.avg_pool2d(im2list[intLevel], kernel_size=2, stride=2))#, count_include_pad=False))

        shape_fine = im2list[self.L - 1].size()
        zeroshape = [batchsize, 2, shape_fine[2] // 2, shape_fine[3] // 2]
        device_id = im1.device.index
        flowfileds = torch.zeros(zeroshape, dtype=torch.float32, device=device_id)
        for intLevel in range(self.L):
            flowfiledsUpsample = bilinearupsacling(flowfileds) * 2.0
            flowfileds = flowfiledsUpsample + self.moduleBasic[intLevel](torch.cat([im1list[self.L - 1 - intLevel], flow_warp(im2list[self.L - 1 - intLevel], flowfiledsUpsample), flowfiledsUpsample], 1))# residualflow

        return flowfileds
    
def motioncompensation(warpnet, ref, mv):
    warpframe = flow_warp(ref, mv)
    inputfeature = torch.cat((warpframe, ref), 1)
    prediction = warpnet(inputfeature) + warpframe
    return prediction, warpframe

def TFE(warpnet,x_ref,bs,mv_hat,layers,parents,use_split,detach=False):
    MC_frame_list = [None for _ in range(bs)]
    warped_frame_list = [None for _ in range(bs)]
    # for layers in graph
    # get elements of this layers
    # get parents of all elements above
    for layer in layers:
        ref = [] # reference frame
        diff = [] # motion
        for tar in layer: # id of frames in this layer
            if tar>bs:continue
            parent = parents[tar]
            ref += [x_ref if parent==0 else MC_frame_list[parent-1]] # ref needed for this id
            diff += [mv_hat[tar-1:tar].cuda(1) if use_split else mv_hat[tar-1:tar]] # motion needed for this id
        if ref:
            ref = torch.cat(ref,dim=0)
            if detach:
                ref = ref.detach()
            diff = torch.cat(diff,dim=0)
            MC_frame,warped_frame = motioncompensation(warpnet, ref, diff)
            for i,tar in enumerate(layer):
                if tar>bs:continue
                MC_frame_list[tar-1] = MC_frame[i:i+1]
                warped_frame_list[tar-1] = warped_frame[i:i+1]
    MC_frames = torch.cat(MC_frame_list,dim=0)
    warped_frames = torch.cat(warped_frame_list,dim=0)
    return MC_frames,warped_frames
                
def TFE2(warpnet,x_ref,bs,mv_hat,layers,parents,use_split):
    warped_frame_list = [None for _ in range(bs)]
    # for layers in graph
    # get elements of this layers
    # get parents of all elements above
    for layer in layers:
        ref = [] # reference frame
        diff = [] # motion
        for tar in layer: # id of frames in this layer
            if tar>bs:continue
            parent = parents[tar]
            ref += [x_ref if parent==0 else warped_frame_list[parent-1]] # ref needed for this id
            diff += [mv_hat[tar-1:tar].cuda(1) if use_split else mv_hat[tar-1:tar]] # motion needed for this id
        if ref:
            ref = torch.cat(ref,dim=0)
            diff = torch.cat(diff,dim=0)
            warped_frame = flow_warp(ref, diff)
            for i,tar in enumerate(layer):
                if tar>bs:continue
                warped_frame_list[tar-1] = warped_frame[i:i+1]
    warped_frames = torch.cat(warped_frame_list,dim=0)
    if bs<6:
        pad = 6-bs
        warped_frames = torch.cat((warped_frames, warped_frames[-1].repeat(pad,1,1,1)), 0)
        mv_hat = torch.cat((mv_hat, mv_hat[-1].repeat(pad,1,1,1)), 0)
    _,_,h,w = mv_hat.size()
    inputfeature = torch.cat((warped_frames, mv_hat), 1)
    prediction = warpnet(inputfeature.view(1,30,h,w)) + warped_frames.view(1,18,h,w)
    MC_frames = prediction.view(6,3,h,w)
    return MC_frames[:bs],warped_frames[:bs]
    
def graph_from_batch(bs,isLinear=False,isOnehop=False):
    if isLinear:
        g,layers,parents = generate_graph('default')
    elif isOnehop:
        g,layers,parents = generate_graph('onehop')
    else:
        # I frame is the only first layer
        if bs <=2:
            g,layers,parents = generate_graph('2layers')
        elif bs <=6:
            g,layers,parents = generate_graph('3layers')
        elif bs <=14:
            g,layers,parents = generate_graph('4layers')
        elif bs <=30:
            g,layers,parents = generate_graph('5layers')
        else:
            print('Batch size not supported yet:',bs)
    return g,layers,parents
    
def refidx_from_graph(g,bs):
    ref_index = [-1 for _ in range(bs)]
    for start in g:
        if start>bs:continue
        for k in g[start]:
            if k>bs:continue
            ref_index[k-1] = start
    return ref_index
        
# DVC,RLVC,MLVC
# Need to measure time and implement decompression for demo
# cache should store start/end-of-GOP information for the action detector to stop; test will be based on it
class IterPredVideoCodecs(nn.Module):
    def __init__(self, name, channels=128, noMeasure=True, loss_type='P',compression_level=2,use_split=True):
        super(IterPredVideoCodecs, self).__init__()
        self.name = name 
        #self.opticFlow = OpticalFlowNet()
        #self.warpnet = MCNet()
        self.opticFlow = ME_Spynet()
        self.warpnet = Warp_net()
        self.mv_codec = Coder2D(self.name, in_channels=2, channels=channels, kernel=3, padding=1, noMeasure=noMeasure)
        self.res_codec = Coder2D(self.name, in_channels=3, channels=channels, kernel=5, padding=2, noMeasure=noMeasure)
        self.channels = channels
        self.loss_type=loss_type
        self.compression_level=compression_level
        self.use_psnr = loss_type=='P'
        init_training_params(self)
        self.epoch = -1
        self.noMeasure = noMeasure
        
        self.use_split = use_split
        if self.use_split:
            self.split()

    def split(self):
        self.opticFlow.cuda(0)
        self.mv_codec.cuda(0)
        self.warpnet.cuda(1)
        self.res_codec.cuda(1)

    def forward(self, Y0_com, Y1_raw, hidden_states, RPM_flag,mv_prior_latent,res_prior_latent):
        # Y0_com: compressed previous frame, [1,c,h,w]
        # Y1_raw: uncompressed current frame
        batch_size, _, Height, Width = Y1_raw.shape
        if self.name == 'RAW':
            bpp_est = bpp_act = metrics = torch.FloatTensor([0]).cuda(0)
            aux_loss = img_loss = torch.FloatTensor([0]).squeeze(0).cuda(0)
            return Y1_raw, hidden_states, bpp_est, img_loss, aux_loss, bpp_act, metrics
        if Y0_com is None:
            Y1_com, bpp_est, img_loss, aux_loss, bpp_act, psnr, msssim = I_compression(Y1_raw, self.I_level)
            return Y1_com, hidden_states, bpp_est, img_loss, aux_loss, bpp_act, psnr, msssim
        # otherwise, it's P frame
        # hidden states
        rae_mv_hidden, rae_res_hidden, rpm_mv_hidden, rpm_res_hidden = hidden_states
        # estimate optical flow
        t_0 = time.perf_counter()
        # replace
        # mv_tensors, l0, l1, l2, l3, l4 = self.opticFlow(Y0_com, Y1_raw)
        mv_tensors = self.opticFlow(Y1_raw, Y0_com)
        if not self.noMeasure:
            self.meters['E-FL'].update(time.perf_counter() - t_0)
        # compress optical flow
        mv_hat,rae_mv_hidden,rpm_mv_hidden,mv_act,mv_est,mv_aux,mv_prior_latent = \
            self.mv_codec(mv_tensors, rae_mv_hidden, rpm_mv_hidden, RPM_flag,prior_latent=mv_prior_latent)
        if not self.noMeasure:
            self.meters['E-MV'].update(self.mv_codec.enc_t)
            self.meters['D-MV'].update(self.mv_codec.dec_t)
            self.meters['eEMV'].update(self.mv_codec.entropy_bottleneck.enc_t)
            self.meters['eDMV'].update(self.mv_codec.entropy_bottleneck.dec_t)
        # motion compensation
        t_0 = time.perf_counter()
        # replace
        Y1_MC, Y1_warp = motioncompensation(self.warpnet, Y0_com, mv_hat.cuda(1) if self.use_split else mv_hat)
        t_comp = time.perf_counter() - t_0
        if not self.noMeasure:
            self.meters['E-MC'].update(t_comp)
            self.meters['D-MC'].update(t_comp)
        # compress residual
        if self.stage == 'RES': Y1_MC = Y1_MC.detach()
        res_tensor = Y1_raw.to(Y1_MC.device) - Y1_MC
        res_hat,rae_res_hidden,rpm_res_hidden,res_act,res_est,res_aux,res_prior_latent = \
            self.res_codec(res_tensor, rae_res_hidden, rpm_res_hidden, RPM_flag,prior_latent=res_prior_latent)
        if not self.noMeasure:
            self.meters['E-RES'].update(self.res_codec.enc_t)
            self.meters['D-RES'].update(self.res_codec.dec_t)
            self.meters['eERES'].update(self.res_codec.entropy_bottleneck.enc_t)
            self.meters['eDRES'].update(self.res_codec.entropy_bottleneck.dec_t)
        # reconstruction
        Y1_com = torch.clip(res_hat + Y1_MC, min=0, max=1)
        ##### compute bits
        # estimated bits
        bpp_est = ((mv_est if self.stage != 'RES' else mv_est.detach()) + \
                (res_est.to(mv_est.device).detach() if self.stage == 'MC' else res_est.to(mv_est.device)))/(Height * Width * batch_size)
        bpp_res_est = (res_est)/(Height * Width * batch_size)
        # actual bits
        bpp_act = (mv_act + res_act.to(mv_act.device))/(Height * Width * batch_size)
        # auxilary loss
        aux_loss = (mv_aux if self.stage != 'RES' else mv_aux.detach()) + \
                    (res_aux.to(mv_aux.device).detach() if self.stage == 'MC' else res_aux.to(mv_aux.device))/2
        # calculate metrics/loss
        psnr = PSNR(Y1_raw, Y1_com.to(Y1_raw.device))
        msssim = PSNR(Y1_raw, Y1_MC.to(Y1_raw.device))
        warp_loss = calc_loss(Y1_raw, Y1_warp.to(Y1_raw.device), 1024, True)
        mc_loss = calc_loss(Y1_raw, Y1_MC.to(Y1_raw.device), 1024, True)
        rec_loss = calc_loss(Y1_raw, Y1_com.to(Y1_raw.device), self.r, self.use_psnr)
        img_loss = mc_loss if self.stage == 'MC' else rec_loss
        # hidden states
        hidden_states = (rae_mv_hidden.detach(), rae_res_hidden.detach(), rpm_mv_hidden, rpm_res_hidden)
        if self.training:
            return Y1_com.to(Y1_raw.device), hidden_states, bpp_est, bpp_res_est, img_loss, aux_loss, bpp_act, psnr, msssim, mv_prior_latent, res_prior_latent
        else:
            return Y1_com.to(Y1_raw.device), hidden_states, bpp_est, img_loss, aux_loss, bpp_act, psnr, msssim, mv_prior_latent, res_prior_latent
        
    def compress(self, Y0_com, Y1_raw, hidden_states, RPM_flag, mv_prior_latent, res_prior_latent):
        bs, c, h, w = Y1_raw[1:].size()
        # hidden states
        rae_mv_hidden, rae_res_hidden, rpm_mv_hidden, rpm_res_hidden = hidden_states
        # estimate optical flow
        t_0 = time.perf_counter()
        #mv_tensors, l0, l1, l2, l3, l4 = self.opticFlow(Y0_com, Y1_raw)
        mv_tensors = self.opticFlow(Y1_raw, Y0_com)
        self.meters['E-FL'].update(time.perf_counter() - t_0)
        # compress optical flow
        mv_hat,mv_string,rae_mv_hidden,rpm_mv_hidden,mv_act,mv_size,mv_prior_latent = \
            self.mv_codec.compress(mv_tensors, rae_mv_hidden, rpm_mv_hidden, RPM_flag, decodeLatent=True, prior_latent=mv_prior_latent)
        self.meters['E-MV'].update(self.mv_codec.net_t + self.mv_codec.AC_t)
        self.meters['eEMV'].update(self.mv_codec.AC_t)
        # motion compensation
        t_0 = time.perf_counter()
        Y1_MC, _ = motioncompensation(self.warpnet, Y0_com, mv_hat.cuda(1) if self.use_split else mv_hat)
        t_comp = time.perf_counter() - t_0
        self.meters['E-MC'].update(t_comp)
        # compress residual
        res_tensor = Y1_raw.to(Y1_MC.device) - Y1_MC
        res_hat,res_string,rae_res_hidden,rpm_res_hidden,res_act,res_size,res_prior_latent = \
            self.res_codec.compress(res_tensor, rae_res_hidden, rpm_res_hidden, RPM_flag, decodeLatent=True, prior_latent=res_prior_latent)
        self.meters['E-RES'].update(self.res_codec.net_t + self.res_codec.AC_t)
        self.meters['eERES'].update(self.res_codec.AC_t)
        # reconstruction
        Y1_com = torch.clip(res_hat + Y1_MC, min=0, max=1).to(Y1_raw.device)
        # hidden states
        hidden_states = (rae_mv_hidden.detach(), rae_res_hidden.detach(), rpm_mv_hidden, rpm_res_hidden)
        self.bitscounter['M'].update(float(mv_act)) 
        self.bitscounter['R'].update(float(res_act)) 
        return Y1_com,mv_string,res_string,hidden_states,mv_prior_latent,res_prior_latent
    
    def decompress(self, x_ref, mv_string, res_string, hidden_states, RPM_flag, mv_prior_latent, res_prior_latent):
        latent_size = torch.Size([16,16])
        # hidden states
        rae_mv_hidden, rae_res_hidden, rpm_mv_hidden, rpm_res_hidden = hidden_states
        # compress optical flow
        mv_hat,rae_mv_hidden,rpm_mv_hidden,mv_prior_latent = self.mv_codec.decompress(mv_string, rae_mv_hidden, rpm_mv_hidden, RPM_flag, latentSize=latent_size, prior_latent=mv_prior_latent)
        self.meters['D-MV'].update(self.mv_codec.net_t + self.mv_codec.AC_t)
        self.meters['eDMV'].update(self.mv_codec.AC_t)
        # motion compensation
        t_0 = time.perf_counter()
        Y1_MC,Y1_warp = motioncompensation(self.warpnet, x_ref, mv_hat.cuda(1) if self.use_split else mv_hat)
        t_comp = time.perf_counter() - t_0
        self.meters['D-MC'].update(t_comp)
        # compress residual
        res_hat,rae_res_hidden,rpm_res_hidden,res_prior_latent = self.res_codec.decompress(res_string, rae_res_hidden, rpm_res_hidden, RPM_flag, latentSize=latent_size, prior_latent=res_prior_latent)
        self.meters['D-RES'].update(self.res_codec.net_t + self.res_codec.AC_t)
        self.meters['eDRES'].update(self.res_codec.AC_t)
        # reconstruction
        Y1_com = torch.clip(res_hat + Y1_MC, min=0, max=1).to(x_ref.device)
        # hidden states
        hidden_states = (rae_mv_hidden.detach(), rae_res_hidden.detach(), rpm_mv_hidden, rpm_res_hidden)
            
        return Y1_com,hidden_states, mv_prior_latent, res_prior_latent
        
    def loss(self, pix_loss, bpp_loss, aux_loss):
        loss = self.r_img*pix_loss + self.r_bpp*bpp_loss + self.r_aux*aux_loss
        return loss
    
    def init_hidden(self, h, w, device):
        rae_mv_hidden = torch.zeros(1,self.channels*4,h//4,w//4)
        rae_res_hidden = torch.zeros(1,self.channels*4,h//4,w//4)
        rpm_mv_hidden = torch.zeros(1,self.channels*2,h//16,w//16)
        rpm_res_hidden = torch.zeros(1,self.channels*2,h//16,w//16)
        rae_mv_hidden = rae_mv_hidden.to(device)
        rae_res_hidden = rae_res_hidden.to(device)
        rpm_mv_hidden = rpm_mv_hidden.to(device)
        rpm_res_hidden = rpm_res_hidden.to(device)
        return (rae_mv_hidden, rae_res_hidden, rpm_mv_hidden, rpm_res_hidden)
        
def TreeFrameReconForward(warpnet,res_codec,x,bs,mv_hat,layers,parents,mode='forward'):
    x_tar = x[1:]
    MC_frame_list = [None for _ in range(bs)]
    warped_frame_list = [None for _ in range(bs)]
    com_frame_list = [None for _ in range(bs)]
    res_act_list = [None for _ in range(bs)]
    res_est_list = [None for _ in range(bs)]
    # for layers in graph
    # get elements of this layers
    # get parents of all elements above
    for layer in layers:
        ref = [] # reference frame
        diff = [] # motion
        target = [] # target frames
        for tar in layer: # id of frames in this layer
            if tar>bs:continue
            parent = parents[tar]
            ref += [x[:1] if parent==0 else com_frame_list[parent-1]] # ref needed for this id
            diff += [mv_hat[tar-1:tar]] # motion needed for this id
            target += [x_tar[tar-1:tar]]
        if ref:
            ref = torch.cat(ref,dim=0)
            diff = torch.cat(diff,dim=0)
            target_frames = torch.cat(target,dim=0)
            MC_frames,warped_frames = motioncompensation(warpnet, ref, diff)
            res_tensors = target_frames - MC_frames
            res_hat,_, _,res_act,res_est,_,_ = res_codec(res_tensors)
            com_frames = torch.clip(res_hat + MC_frames, min=0, max=1)
            for i,tar in enumerate(layer):
                if tar>bs:continue
                MC_frame_list[tar-1] = MC_frames[i:i+1]
                warped_frame_list[tar-1] = warped_frames[i:i+1]
                com_frame_list[tar-1] = com_frames[i:i+1]
                res_act_list[tar-1] = res_act[i:i+1]
                res_est_list[tar-1] = res_est[i:i+1]
    MC_frames = torch.cat(MC_frame_list,dim=0)
    warped_frames = torch.cat(warped_frame_list,dim=0)
    com_frames = torch.cat(com_frame_list,dim=0)
    res_est = torch.cat(res_est_list,dim=0)
    res_act = torch.cat(res_act_list,dim=0)
    res_aux = res_codec.entropy_bottleneck.loss()
    return com_frames,MC_frames,warped_frames,res_act,res_est,res_aux
                  
def TreeFrameReconCompress(warpnet,res_codec,x,bs,mv_hat,layers,parents):
    x_tar = x[1:]
    com_frame_list = [None for _ in range(bs)]
    res_act_list = [None for _ in range(bs)]
    x_string_list = []
    z_string_list = []
    for layer in layers:
        ref = [] # reference frame
        diff = [] # motion
        target = [] # target frames
        for tar in layer: # id of frames in this layer
            if tar>bs:continue
            parent = parents[tar]
            ref += [x[:1] if parent==0 else com_frame_list[parent-1]] # ref needed for this id
            diff += [mv_hat[tar-1:tar]] # motion needed for this id
            target += [x_tar[tar-1:tar]]
        if ref:
            ref = torch.cat(ref,dim=0)
            diff = torch.cat(diff,dim=0)
            target_frames = torch.cat(target,dim=0)
            MC_frames,warped_frames = motioncompensation(warpnet, ref, diff)
            res_tensors = target_frames - MC_frames
            res_hat,res_string,_,_,res_act,res_size,_ = res_codec.compress(res_tensors,decodeLatent=True)
            x_string_list += res_string[0]
            z_string_list += res_string[1]
            com_frames = torch.clip(res_hat + MC_frames, min=0, max=1)
            for i,tar in enumerate(layer):
                if tar>bs:continue
                com_frame_list[tar-1] = com_frames[i:i+1]
                res_act_list[tar-1] = res_act[i:i+1]
    res_act = torch.cat(res_act_list,dim=0)
    return (x_string_list,z_string_list),res_act
                              
def TreeFrameReconDecompress(warpnet,res_codec,x_ref,res_string,bs,mv_hat,layers,parents):
    com_frame_list = [None for _ in range(bs)]
    x_string_list,z_string_list = res_string
    for layer in layers:
        ref = [] # reference frame
        diff = [] # motion
        for tar in layer: # id of frames in this layer
            if tar>bs:continue
            parent = parents[tar]
            ref += [x_ref if parent==0 else com_frame_list[parent-1]] # ref needed for this id
            diff += [mv_hat[tar-1:tar]] # motion needed for this id
        if ref:
            ref = torch.cat(ref,dim=0)
            diff = torch.cat(diff,dim=0)
            MC_frames,warped_frames = motioncompensation(warpnet, ref, diff)
            res_string = ([x_string_list.pop(0)],[z_string_list.pop(0)])
            latent_size = torch.Size([ref.size(0),16,16])
            res_hat,_,_,_ = res_codec.decompress(res_string, latentSize=latent_size)
            com_frames = torch.clip(res_hat + MC_frames, min=0, max=1)
            for i,tar in enumerate(layer):
                if tar>bs:continue
                com_frame_list[tar-1] = com_frames[i:i+1]
    com_frames = torch.cat(com_frame_list,dim=0)
    return com_frames

class SPVC(nn.Module):
    def __init__(self, name, channels=64, noMeasure=True, loss_type='P', 
            compression_level=2, use_split=True, entropy_trick=True):
        super(SPVC, self).__init__()
        self.name = name 
        #self.opticFlow = OpticalFlowNet()
        #self.warpnet = MCNet()
        self.opticFlow = ME_Spynet()
        self.warpnet = Warp_net()
            
        if '96' in self.name:
            channels = 96
        elif '128' in self.name:
            channels = 128
        if '-L' in self.name:
            entropy_trick = False
        # use attention in encoder and entropy model
        self.mv_codec = Coder2D('mshp', in_channels=2, channels=channels, kernel=3, padding=1, noMeasure=noMeasure, entropy_trick=entropy_trick)
        if '-P' in self.name:
            res_type = 'mshp' # plain type
        else:
            res_type = 'attn'
        self.res_codec = Coder2D(res_type, in_channels=3, channels=channels, kernel=5, padding=2, noMeasure=noMeasure, entropy_trick=entropy_trick)
        self.channels = channels
        self.loss_type=loss_type
        self.compression_level=compression_level
        self.use_psnr = loss_type=='P'
        init_training_params(self)
        self.use_split = use_split
        if self.use_split:
            self.split()
        else:
            self = self.cuda()
        self.noMeasure = noMeasure
        self.entropy_trick = entropy_trick

    def split(self):
        self.opticFlow.cuda(0)
        self.mv_codec.cuda(0)
        self.warpnet.cuda(1)
        self.res_codec.cuda(1)
        
    def compress(self, x):
        bs, c, h, w = x[1:].size()
        
        # BATCH:compute optical flow
        t_0 = time.perf_counter()
        # obtain reference frames from a graph
        x_tar = x[1:]
        g,layers,parents = graph_from_batch(bs,isLinear=('-L' in self.name),isOnehop=('-O' in self.name)) # or one-hop?
        ref_index = refidx_from_graph(g,bs)
        mv_tensors = self.opticFlow(x_tar,x[ref_index])
        self.meters['E-FL'].update(time.perf_counter() - t_0)
            
        # BATCH motion compression
        mv_hat,mv_string,_,_,mv_act,mv_size,_ = self.mv_codec.compress(mv_tensors,decodeLatent=True)
        self.meters['E-MV'].update(self.mv_codec.net_t + self.mv_codec.AC_t)
        self.meters['eEMV'].update(self.mv_codec.AC_t)
        
        # SEQ:motion compensation
        t_0 = time.perf_counter()
        res_string,res_act = TreeFrameReconCompress(self.warpnet,self.res_codec,x,bs,mv_hat,layers,parents)
        t_comp = time.perf_counter() - t_0
        self.meters['E-MC'].update(t_comp)
        
        # actual bits
        # self.bitscounter['M'].update(float(mv_act)) 
        # self.bitscounter['R'].update(float(torch.sum(res_act))) 
        bpp_act = (mv_act + res_act.to(mv_act.device))/(h * w)
        bpp_act = [bpp for bpp in bpp_act]
        
        return mv_string,res_string,bpp_act
        
    def decompress(self, x_ref, mv_string,res_string,bs):
        latent_size = torch.Size([bs,16,16]) if self.entropy_trick else torch.Size([16,16])
        # BATCH motion decode
        mv_hat,_,_,_ = self.mv_codec.decompress(mv_string, latentSize=latent_size)
        self.meters['D-MV'].update(self.mv_codec.net_t + self.mv_codec.AC_t)
        self.meters['eDMV'].update(self.mv_codec.AC_t)
        
        # graph
        g,layers,parents = graph_from_batch(bs,isLinear=('-L' in self.name),isOnehop=('-O' in self.name))
        
        t_0 = time.perf_counter()
        com_frames = TreeFrameReconDecompress(self.warpnet,self.res_codec,x_ref,res_string,bs,mv_hat,layers,parents)
        t_comp = time.perf_counter() - t_0
        self.meters['D-MC'].update(t_comp)
        
        return com_frames
        
    def forward(self, x):
        bs, c, h, w = x[1:].size()
        
        # BATCH:compute optical flow
        t_0 = time.perf_counter()
        # obtain reference frames from a graph
        x_tar = x[1:]
        g,layers,parents = graph_from_batch(bs,isLinear=('-L' in self.name),isOnehop=('-O' in self.name))
        ref_index = refidx_from_graph(g,bs)
        mv_tensors = self.opticFlow(x_tar,x[ref_index])
        if not self.noMeasure:
            self.meters['E-FL'].update(time.perf_counter() - t_0)
            
        # BATCH:compress optical flow
        mv_hat,_,_,mv_act,mv_est,mv_aux,_ = self.mv_codec(mv_tensors)
        if not self.noMeasure:
            self.meters['E-MV'].update(self.mv_codec.enc_t)
            self.meters['D-MV'].update(self.mv_codec.dec_t)
            self.meters['eEMV'].update(self.mv_codec.entropy_bottleneck.enc_t)
            self.meters['eDMV'].update(self.mv_codec.entropy_bottleneck.dec_t)

        # new compression way
        com_frames,MC_frames,warped_frames,res_act,res_est,res_aux = TreeFrameReconForward(self.warpnet,self.res_codec,x,bs,mv_hat,layers,parents)
            
        ##### compute bits
        # estimated bits
        bpp_est = ((mv_est) + \
                (res_est.to(mv_est.device).detach() if self.stage == 'MC' else res_est.to(mv_est.device)))/(h * w)
        bpp_res_est = (res_est)/(h * w)
        # actual bits
        bpp_act = (mv_act + res_act.to(mv_act.device))/(h * w)
        # auxilary loss
        aux_loss = (mv_aux) + \
                    (res_aux.to(mv_aux.device).detach() if self.stage == 'MC' else res_aux.to(mv_aux.device))
        aux_loss = aux_loss.repeat(bs)
        # calculate metrics/loss
        psnr = PSNR(x_tar, com_frames, use_list=True)
        msssim = PSNR(x_tar, MC_frames, use_list=True)
        #print([float(m) for m in msssim])
        mc_loss = calc_loss(x_tar, MC_frames, self.r, True)
        #warp_loss = calc_loss(x_tar, warped_frames, self.r, True)
        rec_loss = calc_loss(x_tar, com_frames, self.r, self.use_psnr)
        if self.stage == 'MC':
            img_loss = mc_loss
        elif self.stage == 'REC':
            img_loss = rec_loss
        else:
            print('unknown stage')
            exit(1)
        img_loss = img_loss.repeat(bs)
        
        if self.training:
            return com_frames, bpp_est, bpp_res_est, img_loss, aux_loss, bpp_act, psnr, msssim
        else:
            return com_frames, bpp_est, img_loss, aux_loss, bpp_act, psnr, msssim
    
    def loss(self, pix_loss, bpp_loss, aux_loss):
        loss = self.r_img*pix_loss.cuda(0) + self.r_bpp*bpp_loss.cuda(0) + self.r_aux*aux_loss.cuda(0)
        return loss
        
    def init_hidden(self, h, w, device):
        return None

from DVC.subnet import Analysis_mv_net,Synthesis_mv_net,Analysis_prior_net,Synthesis_prior_net,Analysis_net,Synthesis_net,BitEstimator,out_channel_M,out_channel_N,out_channel_mv

class LSVC(nn.Module):
    def __init__(self, name, loss_type='P', compression_level=3, use_split=True):
        super(LSVC, self).__init__()
        self.name = name
        self.useAttn = True if '-A' in name else False
        self.opticFlow = ME_Spynet()
        self.Q = None
        useAttn = ('-A' in name)
        channels = 128 if '-128' in name else out_channel_M 
        self.mvEncoder = Analysis_mv_net(useAttn=useAttn,channels=channels)
        self.mvDecoder = Synthesis_mv_net(channels=channels)
        self.resEncoder = Analysis_net(useAttn=useAttn)
        self.resDecoder = Synthesis_net()
        self.respriorEncoder = Analysis_prior_net(useAttn=useAttn)
        self.respriorDecoder = Synthesis_prior_net()
        self.bitEstimator_mv = BitEstimator(channels)
        self.bitEstimator_z = BitEstimator(out_channel_N)
        self.warpnet = Warp_net()
        self.warp_weight = 0
        self.mxrange = 150
        self.calrealbits = False
        self.loss_type=loss_type
        self.channels = channels
        self.compression_level=compression_level
        init_training_params(self)
        self.use_split = use_split
        if self.use_split:
            self.split()
        
    def split(self):
        self.opticFlow.cuda(0)
        self.mvEncoder.cuda(0)
        self.mvDecoder.cuda(0)
        self.bitEstimator_mv.cuda(0)
        self.warpnet.cuda(1)
        self.resEncoder.cuda(1)
        self.resDecoder.cuda(1)
        self.respriorEncoder.cuda(1)
        self.respriorDecoder.cuda(1)
        self.bitEstimator_z.cuda(1)

    def motioncompensation(self, ref, mv):
        warpframe = flow_warp(ref, mv)
        inputfeature = torch.cat((warpframe, ref), 1)
        if self.use_split:
            inputfeature = inputfeature.cuda(1)
        a = self.warpnet(inputfeature)
        if self.use_split:
            a = a.cuda(0)
        prediction = a + warpframe
        return prediction, warpframe

    def feature_probs_based_sigma(self,feature, sigma):
            
        def getrealbitsg(x, gaussian):
            # print("NIPS18noc : mn : ", torch.min(x), " - mx : ", torch.max(x), " range : ", self.mxrange)
            cdfs = []
            x = x + self.mxrange
            n,c,h,w = x.shape
            for i in range(-self.mxrange, self.mxrange):
                cdfs.append(gaussian.cdf(i - 0.5).view(n,c,h,w,1))
            cdfs = torch.cat(cdfs, 4).cpu().detach()
            
            byte_stream = torchac.encode_float_cdf(cdfs, x.cpu().detach().to(torch.int16), check_input_bounds=True)

            real_bits = torch.from_numpy(np.array([len(byte_stream) * 8])).float().cuda()

            sym_out = torchac.decode_float_cdf(cdfs, byte_stream)

            return sym_out - self.mxrange, real_bits

        mu = torch.zeros_like(sigma)
        sigma = sigma.clamp(1e-5, 1e10)
        gaussian = torch.distributions.laplace.Laplace(mu, sigma)
        probs = gaussian.cdf(feature + 0.5) - gaussian.cdf(feature - 0.5)
        total_bits = torch.sum(torch.clamp(-1.0 * torch.log(probs + 1e-5) / math.log(2.0), 0, 50))
        
        if self.calrealbits and not self.training:
            decodedx, real_bits = getrealbitsg(feature, gaussian)
            total_bits = real_bits

        return total_bits, probs

    def iclr18_estrate_bits_z(self,z):
        
        def getrealbits(x):
            cdfs = []
            x = x + self.mxrange
            n,c,h,w = x.shape
            for i in range(-self.mxrange, self.mxrange):
                cdfs.append(self.bitEstimator_z(i - 0.5).view(1, c, 1, 1, 1).repeat(n, 1, h, w, 1))
            cdfs = torch.cat(cdfs, 4).cpu().detach()
            byte_stream = torchac.encode_float_cdf(cdfs, x.cpu().detach().to(torch.int16), check_input_bounds=True)

            real_bits = torch.sum(torch.from_numpy(np.array([len(byte_stream) * 8])).float().cuda())

            sym_out = torchac.decode_float_cdf(cdfs, byte_stream)

            return sym_out - self.mxrange, real_bits

        prob = self.bitEstimator_z(z + 0.5) - self.bitEstimator_z(z - 0.5)
        total_bits = torch.sum(torch.clamp(-1.0 * torch.log(prob + 1e-5) / math.log(2.0), 0, 50))


        if self.calrealbits and not self.training:
            decodedx, real_bits = getrealbits(z)
            total_bits = real_bits

        return total_bits, prob


    def iclr18_estrate_bits_mv(self,mv):

        def getrealbits(x):
            cdfs = []
            x = x + self.mxrange
            n,c,h,w = x.shape
            for i in range(-self.mxrange, self.mxrange):
                cdfs.append(self.bitEstimator_mv(i - 0.5).view(1, c, 1, 1, 1).repeat(n, 1, h, w, 1))
            cdfs = torch.cat(cdfs, 4).cpu().detach()
            byte_stream = torchac.encode_float_cdf(cdfs, x.cpu().detach().to(torch.int16), check_input_bounds=True)

            real_bits = torch.sum(torch.from_numpy(np.array([len(byte_stream) * 8])).float().cuda())

            sym_out = torchac.decode_float_cdf(cdfs, byte_stream)
            return sym_out - self.mxrange, real_bits

        prob = self.bitEstimator_mv(mv + 0.5) - self.bitEstimator_mv(mv - 0.5)
        total_bits = torch.sum(torch.clamp(-1.0 * torch.log(prob + 1e-5) / math.log(2.0), 0, 50))


        if self.calrealbits and not self.training:
            decodedx, real_bits = getrealbits(mv)
            total_bits = real_bits

        return total_bits, prob

    def res_codec(self,input_residual):
        if self.use_split:
            input_residual = input_residual.cuda(1)
        feature = self.resEncoder(input_residual)
        z = self.respriorEncoder(feature)

        if self.training:
            half = float(0.5)
            noise = torch.empty_like(z).uniform_(-half, half)
            compressed_z = z + noise
        else:
            compressed_z = torch.round(z)

        recon_sigma = self.respriorDecoder(compressed_z)

        feature_renorm = feature

        if self.training:
            half = float(0.5)
            noise = torch.empty_like(feature_renorm).uniform_(-half, half)
            compressed_feature_renorm = feature_renorm + noise
        else:
            compressed_feature_renorm = torch.round(feature_renorm)

        recon_res = self.resDecoder(compressed_feature_renorm)

        total_bits_feature, _ = self.feature_probs_based_sigma(compressed_feature_renorm, recon_sigma)
        total_bits_z, _ = self.iclr18_estrate_bits_z(compressed_z)
        total_bits = total_bits_feature+total_bits_z
        if self.use_split:
            recon_res = recon_res.cuda(0)
            total_bits = total_bits.cuda(0)
        return recon_res,total_bits

    def mv_codec(self, estmv):
        mvfeature = self.mvEncoder(estmv)
        if self.training:
            half = float(0.5)
            noise = torch.empty_like(mvfeature).uniform_(-half, half)
            quant_mv = mvfeature + noise
        else:
            quant_mv = torch.round(mvfeature)
        quant_mv_upsample = self.mvDecoder(quant_mv)
        total_bits, _ = self.iclr18_estrate_bits_mv(quant_mv)
        return quant_mv_upsample,total_bits

    def forward(self, x):
        input_image = x[1:]
        bs,c,h,w = input_image.size()

        g,layers,parents = graph_from_batch(bs,isLinear=('-L' in self.name),isOnehop=('-O' in self.name))
        ref_index = refidx_from_graph(g,bs)
        estmv = self.opticFlow(input_image, x[ref_index])
        quant_mv_upsample,total_bits_mv = self.mv_codec(estmv)

        # tree compensation
        MC_frame_list = [None for _ in range(bs)]
        warped_frame_list = [None for _ in range(bs)]
        com_frame_list = [None for _ in range(bs)]
        total_bits_res = None
        x_tar = x[1:]
        for layer in layers:
            ref = [] # reference frame
            diff = [] # motion
            target = [] # target frames
            for tar in layer: # id of frames in this layer
                if tar>bs:continue
                parent = parents[tar]
                ref += [x[:1] if parent==0 else com_frame_list[parent-1]] # ref needed for this id
                diff += [quant_mv_upsample[tar-1:tar]] # motion needed for this id
                target += [x_tar[tar-1:tar]]
            if ref:
                ref = torch.cat(ref,dim=0)
                # if linear or detach, detach it. dont care one-hop
                if '-L' in self.name or '-D' in self.name:
                    ref = ref.detach()
                diff = torch.cat(diff,dim=0)
                target_frames = torch.cat(target,dim=0)
                MC_frames,warped_frames = self.motioncompensation(ref, diff)
                #print(PSNR(target_frames, MC_frames, use_list=True))
                approx_frames = MC_frames
                res_tensors = target_frames - approx_frames
                res_hat,res_bits = self.res_codec(res_tensors)
                com_frames = torch.clip(res_hat + approx_frames, min=0, max=1)
                for i,tar in enumerate(layer):
                    if tar>bs:continue
                    MC_frame_list[tar-1] = MC_frames[i:i+1]
                    warped_frame_list[tar-1] = warped_frames[i:i+1]
                    com_frame_list[tar-1] = com_frames[i:i+1]
                if total_bits_res is None:
                    total_bits_res = res_bits
                else:
                    total_bits_res += res_bits
        MC_frames = torch.cat(MC_frame_list,dim=0)
        warped_frames = torch.cat(warped_frame_list,dim=0)
        com_frames = torch.cat(com_frame_list,dim=0)

        rec_loss = torch.mean((com_frames - input_image).pow(2))
        warp_loss = torch.mean((warped_frames - input_image).pow(2))
        mc_loss = torch.mean((MC_frames - input_image).pow(2))
        
        bpp_res = total_bits_res / (bs * h * w)
        bpp_mv = total_bits_mv / (bs * h * w)
        if self.stage == 'MC' or self.stage == 'WP': bpp_res = bpp_res.detach()
        bpp = bpp_res + bpp_mv
        
        return com_frames, MC_frames, warped_frames, rec_loss, warp_loss, mc_loss, bpp_res, bpp
       
# need a new RLVC model for accuracy test

class AE3D(nn.Module):
    def __init__(self, name, noMeasure=True, loss_type='P', compression_level=2, use_split=True):
        super(AE3D, self).__init__()
        self.name = name 
        self.conv1 = nn.Sequential(
            nn.Conv3d(3, 64, kernel_size=5, stride=(1,2,2), padding=2), 
            nn.BatchNorm3d(64),
            nn.ReLU(inplace=True),
            nn.Conv3d(64, 128, kernel_size=5, stride=(1,2,2), padding=2), 
            nn.BatchNorm3d(128),
            nn.ReLU(inplace=True),
        )
        self.conv2 = nn.Sequential(
            ResBlockB(),
            ResBlockB(),
            ResBlockB(),
            ResBlockB(),
            ResBlockB(),
            ResBlockA(),
        )
        self.conv3 = nn.Sequential(
            nn.Conv3d(128, 32, kernel_size=5, stride=(1,2,2), padding=2), 
            nn.BatchNorm3d(32),
            nn.ReLU(inplace=True),
        )
        self.latent_codec = Coder2D('rpm', channels=32, kernel=5, padding=2, noMeasure=noMeasure, downsample=False)
        self.deconv1 = nn.Sequential( 
            nn.ConvTranspose3d(32, 128, kernel_size=5, stride=(1,2,2), padding=2, output_padding=(0,1,1)),
            nn.BatchNorm3d(128),
            nn.ReLU(inplace=True),
        )
        self.deconv2 = nn.Sequential(
            ResBlockB(),
            ResBlockB(),
            ResBlockB(),
            ResBlockB(),
            ResBlockB(),
            ResBlockA(),
        )
        self.deconv3 = nn.Sequential( 
            nn.ConvTranspose3d(128, 64, kernel_size=5, stride=(1,2,2), padding=2, output_padding=(0,1,1)),
            nn.BatchNorm3d(64),
            nn.ReLU(inplace=True),
            nn.ConvTranspose3d(64, 3, kernel_size=5, stride=(1,2,2), padding=2, output_padding=(0,1,1)),
            nn.BatchNorm3d(3),
        )
        self.channels = 128
        self.loss_type=loss_type
        self.compression_level=compression_level
        self.use_psnr = loss_type=='P'
        init_training_params(self)
        self.use_split = use_split
        if use_split:
            self.split()
        else:
            self = self.cuda()
        self.noMeasure = noMeasure

    def split(self):
        # too much on cuda:0
        self.conv1.cuda(0)
        self.conv2.cuda(0)
        self.conv3.cuda(0)
        self.deconv1.cuda(1)
        self.deconv2.cuda(1)
        self.deconv3.cuda(1)
        self.latent_codec.cuda(0)
        
    def forward(self, x):
        t_0 = time.perf_counter()
        x = x[1:]
            
        # x=[B,C,H,W]: input sequence of frames
        x = x.permute(1,0,2,3).contiguous().unsqueeze(0)
        bs, c, t, h, w = x.size()
        
        # encoder
        x1 = self.conv1(x)
        x2 = self.conv2(x1) + x1
        latent = self.conv3(x2)
        if not self.noMeasure:
            self.meters['E-NET'].update(time.perf_counter() - t_0)
        
        # entropy
        # compress each frame sequentially
        latent = latent.squeeze(0).permute(1,0,2,3).contiguous()
        latent_hat,latent_act,latent_est,aux_loss = self.latent_codec.compress_sequence(latent)
        latent_hat = latent_hat.permute(1,0,2,3).unsqueeze(0).contiguous()
        if not self.noMeasure:
            self.meters['E-MV'].update(self.latent_codec.enc_t)
            self.meters['D-MV'].update(self.latent_codec.dec_t)
        
        # decoder
        t_0 = time.perf_counter()
        x3 = self.deconv1(latent_hat.cuda(1) if self.use_split else latent_hat)
        x4 = self.deconv2(x3) + x3
        x_hat = self.deconv3(x4)
        
        # reshape
        x = x.permute(0,2,1,3,4).contiguous().squeeze(0)
        x_hat = x_hat.permute(0,2,1,3,4).contiguous().squeeze(0)
        if not self.noMeasure:
            self.meters['D-NET'].update(time.perf_counter() - t_0)
        
        # estimated bits
        bpp_est = latent_est/(h * w)
        
        # actual bits
        bpp_act = latent_act/(h * w)
        
        # aux loss
        aux_loss = aux_loss.repeat(bs)
        
        # calculate metrics/loss
        psnr = PSNR(x, x_hat, use_list=True)
        msssim = MSSSIM(x, x_hat, use_list=True)
        
        # calculate img loss
        img_loss = calc_loss(x, x_hat.to(x.device), self.r, self.use_psnr)
        img_loss = img_loss.repeat(t)
        
        return x_hat.to(x.device), bpp_est, img_loss, aux_loss, bpp_act, psnr, msssim
    
    def init_hidden(self, h, w, device):
        return None
        
    def loss(self, pix_loss, bpp_loss, aux_loss, app_loss=None):
        loss = self.r_img*pix_loss.cuda(0) + self.r_bpp*bpp_loss.cuda(0) + self.r_aux*aux_loss.cuda(0)
        if app_loss is not None:
            loss += self.r_app*app_loss.cuda(0)
        return loss
        
class ResBlockA(nn.Module):
    "A ResNet-like block with the GroupNorm normalization providing optional bottle-neck functionality"
    def __init__(self, ch=128, k_size=3, stride=1, p=1):
        super(ResBlockA, self).__init__()
        self.conv = nn.Sequential(
            nn.Conv3d(ch, ch, kernel_size=k_size, stride=stride, padding=p), 
            nn.BatchNorm3d(ch),
            nn.ReLU(inplace=True),

            nn.Conv3d(ch, ch, kernel_size=k_size, stride=stride, padding=p),  
            nn.BatchNorm3d(ch),
        )
        
    def forward(self, x):
        out = self.conv(x) + x
        return out
        
class ResBlockB(nn.Module):
    def __init__(self, ch=128, k_size=3, stride=1, p=1):
        super(ResBlockB, self).__init__()
        self.conv = nn.Sequential(
            ResBlockA(ch, k_size, stride, p), 
            ResBlockA(ch, k_size, stride, p), 
            ResBlockA(ch, k_size, stride, p), 
        )
        
    def forward(self, x):
        out = self.conv(x) + x
        return out
        
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
        
def test_batch_proc(name = 'SPVC',batch_size = 6):
    print('------------',name,'------------')
    
    h = w = 256
    channels = 96
    x = torch.randn(batch_size+1,3,h,w).cuda()
    if 'SPVC' in name:
        model = SPVC(name,channels,noMeasure=False,use_split=False)
    elif name == 'AE3D':
        model = AE3D(name,noMeasure=False,use_split=False)
    else:
        print('Not implemented.')
    from tqdm import tqdm
    timer = AverageMeter()
    train_iter = tqdm(range(0,1))
    model.eval()
    # warmup
    mv_string,res_string,bpp_act = model.compress(x)
    for i,_ in enumerate(train_iter):
        # measure start
        bs = x.size(0)-1
        t_0 = time.perf_counter()
        mv_string,res_string,bpp_act = model.compress(x)
        # x_hat = model.decompress(x[:1],mv_string,res_string,bs)
        # com_frames, bpp_est, img_loss, aux_loss, bpp_act, psnr, sim = model(x)
        d = (time.perf_counter() - t_0)
        timer.update(d)
        # measure end
        usage = torch.cuda.memory_allocated()/(1024**3)
        
        train_iter.set_description(
            f"{batch_size}: {i:4}. "
            f"bits_act: {float(bpp_act[-1]):.2f}. "
            f"duration: {timer.sum:.3f}. "
            f"gpu usage: {usage:.3f}. ")
    _,_,enc,dec = showTimer(model)
    return timer.sum
            
def test_seq_proc(name='RLVC',batch_size = 13):
    print('------------',name,'------------')
    h = w = 224
    x = torch.rand(1,3,h,w).cuda()
    model = IterPredVideoCodecs(name,noMeasure=False,use_split=False)
    from tqdm import tqdm
    timer = AverageMeter()
    hidden_states = model.init_hidden(h,w)
    train_iter = tqdm(range(0,batch_size))
    model.eval()
    x_hat_prev = x
    mv_prior_latent=res_prior_latent=None
    # warm-up
    x_hat,mv_string,res_string,hidden_states,mv_prior_latent,res_prior_latent = \
        model.compress(x, x_hat_prev, hidden_states, False, mv_prior_latent, res_prior_latent)
    for i,_ in enumerate(train_iter):
        # measure start
        t_0 = time.perf_counter()
        x_hat,mv_string,res_string,hidden_states,mv_prior_latent,res_prior_latent = \
            model.compress(x, x_hat_prev, hidden_states, i!=0, mv_prior_latent, res_prior_latent)
        d = time.perf_counter() - t_0
        timer.update(d)
        # measure end
        x_hat_prev = x_hat.detach()
        usage = torch.cuda.memory_allocated()/(1024**3)
        
        train_iter.set_description(
            f"Batch: {i:4}. "
            f"duration: {timer.sum:.3f}. "
            f"gpu usage: {usage:.3f}. ")
    _,_,enc,dec = showTimer(model)
    return timer.sum

def get_DVC_pretrained(level):
    from DVC.net import VideoCompressor, load_model
    model = VideoCompressor()
    model.name = 'DVC-pretrained'
    model.compression_level = level
    model.loss_type = 'P'
    ratio_list = [256,512,1024,2048]
    I_lvl_list = [37,32,27,22]
    model.I_level = I_lvl_list[level]
    def loss(pix_loss, bpp_loss, aux_loss):
        return pix_loss + bpp_loss + aux_loss
    model.loss = loss
    global_step = load_model(model, f'DVC/snapshot/{ratio_list[level]}.model')
    net = model.cuda()
    return net
            
# integrate all codec models
# measure the speed of all codecs
# two types of test
# 1. (de)compress random images, faster
# 2. (de)compress whole datasets, record time during testing 
# need to implement 3D-CNN compression
# ***************each model can have a timer member that counts enc/dec time
# in training, counts total time, in testing, counts enc/dec time
# how to deal with big batch in training? hybrid mode
# update CNN alternatively?
    
if __name__ == '__main__':
    emb = Embeddings()
    x = torch.zeros(2,3)
    output = emb(x)
    print(output)
    exit(0)
    result_dvc = []
    result_rlvc = []
    result_spvc = []
    for B in range(1,15):
        dvc_t = test_seq_proc('DVC',B)
        rlvc_t = test_seq_proc('RLVC',B)
        spvc_t = test_batch_proc('SPVC', B)
        result_dvc += [dvc_t]
        result_rlvc += [rlvc_t]
        result_spvc += [spvc_t]
    print(result_dvc)
    print(result_rlvc)
    print(result_spvc)
    test_batch_proc('AE3D')
    test_batch_proc('SPVC-L')
    test_batch_proc('SPVC-R')
    test_batch_proc('SCVC')