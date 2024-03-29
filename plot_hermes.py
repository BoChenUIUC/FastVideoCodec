#!/usr/bin/python

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import os
lfsize = 18
labelsize = 24
labelsize_s,labelsize_b = 24,32
linewidth = 4
plt.rcParams['xtick.labelsize'] = 20
plt.rcParams['ytick.labelsize'] = 20
plt.rcParams["font.family"] = "Times New Roman"
colors = ['#DB1F48','#FF9636','#1C4670','#9D5FFB','#21B6A8','#D65780']
# colors = ['#D00C0E','#E09C1A','#08A720','#86A8E7','#9D5FFB','#D65780']
labels = ['ELVC','H.264','H.265','DVC','RLVC']
markers = ['o','P','s','D','>','^','<','v','*']
hatches = ['/' ,'\\','--','x', '+', 'O','-','o','.','*']
linestyles = ['solid','dotted','dashed','dashdot', (0, (3, 5, 1, 5, 1, 5))]
from collections import OrderedDict
linestyle_dict = OrderedDict(
    [('solid',               (0, ())),
     ('dotted',              (0, (1, 5))),
     ('densely dotted',      (0, (1, 1))),

     ('loosely dashed',      (0, (5, 10))),
     ('dashed',              (0, (5, 5))),
     ('densely dashed',      (0, (5, 1))),

     ('dashdotted',          (0, (3, 5, 1, 5))),
     ('densely dashdotted',  (0, (3, 1, 1, 1))),

     ('dashdotdotted',         (0, (3, 5, 1, 5, 1, 5))),
     ('densely dashdotdotted', (0, (3, 1, 1, 1, 1, 1)))])
linestyles = []
for i, (name, linestyle) in enumerate(linestyle_dict.items()):
    if i >= 9:break
    linestyles += [linestyle]

import scipy.interpolate

def BD_PSNR(R1, PSNR1, R2, PSNR2, piecewise=0):
    lR1 = np.log(R1)
    lR2 = np.log(R2)

    PSNR1 = np.array(PSNR1)
    PSNR2 = np.array(PSNR2)

    p1 = np.polyfit(lR1, PSNR1, 3)
    p2 = np.polyfit(lR2, PSNR2, 3)

    # integration interval
    min_int = max(min(lR1), min(lR2))
    max_int = min(max(lR1), max(lR2))

    # find integral
    if piecewise == 0:
        p_int1 = np.polyint(p1)
        p_int2 = np.polyint(p2)

        int1 = np.polyval(p_int1, max_int) - np.polyval(p_int1, min_int)
        int2 = np.polyval(p_int2, max_int) - np.polyval(p_int2, min_int)
    else:
        # See https://chromium.googlesource.com/webm/contributor-guide/+/master/scripts/visual_metrics.py
        lin = np.linspace(min_int, max_int, num=100, retstep=True)
        interval = lin[1]
        samples = lin[0]
        v1 = scipy.interpolate.pchip_interpolate(np.sort(lR1), PSNR1[np.argsort(lR1)], samples)
        v2 = scipy.interpolate.pchip_interpolate(np.sort(lR2), PSNR2[np.argsort(lR2)], samples)
        # Calculate the integral using the trapezoid method on the samples.
        int1 = np.trapz(v1, dx=interval)
        int2 = np.trapz(v2, dx=interval)

    # find avg diff
    avg_diff = (int2-int1)/(max_int-min_int)

    return avg_diff


def BD_RATE(R1, PSNR1, R2, PSNR2, piecewise=0):
    lR1 = np.log(R1)
    lR2 = np.log(R2)

    # rate method
    p1 = np.polyfit(PSNR1, lR1, 3)
    p2 = np.polyfit(PSNR2, lR2, 3)

    # integration interval
    min_int = max(min(PSNR1), min(PSNR2))
    max_int = min(max(PSNR1), max(PSNR2))

    # find integral
    if piecewise == 0:
        p_int1 = np.polyint(p1)
        p_int2 = np.polyint(p2)

        int1 = np.polyval(p_int1, max_int) - np.polyval(p_int1, min_int)
        int2 = np.polyval(p_int2, max_int) - np.polyval(p_int2, min_int)
    else:
        lin = np.linspace(min_int, max_int, num=100, retstep=True)
        interval = lin[1]
        samples = lin[0]
        v1 = scipy.interpolate.pchip_interpolate(np.sort(PSNR1), lR1[np.argsort(PSNR1)], samples)
        v2 = scipy.interpolate.pchip_interpolate(np.sort(PSNR2), lR2[np.argsort(PSNR2)], samples)
        # Calculate the integral using the trapezoid method on the samples.
        int1 = np.trapz(v1, dx=interval)
        int2 = np.trapz(v2, dx=interval)

    # find avg diff
    avg_exp_diff = (int2-int1)/(max_int-min_int)
    avg_diff = (np.exp(avg_exp_diff)-1)*100
    return avg_diff

########################NETWORK IMPACT#####################
# FPS,Rebuffer,Latency
def get_mean_std_from(pos,filename):
	arr = [[[] for _ in range(4)] for _ in range(5)]
	with open(filename,'r') as f:
		count = 0
		for line in f.readlines():
			line = line.strip()
			line = line.split(' ')
			v = float(line[pos])
			i = (count%20)//4 # method
			j = (count%20)%4 # lambda value
			arr[i][j] += [v]
			count += 1
	arr = np.array(arr)
	arr.resize(5,4*len(arr[0][0]))
	avg = np.mean(arr,1)
	std = np.std(arr,1)
	return avg,std

def get_arr_from(pos,filename):
	arr = [[[] for _ in range(4)] for _ in range(5)]
	with open(filename,'r') as f:
		count = 0
		for line in f.readlines():
			line = line.strip()
			line = line.split(' ')
			v = float(line[pos])
			i = (count%20)//4 # method
			j = (count%20)%4 # lambda value
			arr[i][j] += [v]
			count += 1
	arr = np.array(arr)
	return arr

def line_plot(XX,YY,label,color,path,xlabel,ylabel,lbsize=labelsize_b,lfsize=labelsize_b-8,legloc='best',
				xticks=None,yticks=None,xticklabel=None,yticklabel=None,ncol=None, yerr=None,markers=markers,xlim=None,ylim=None,
				use_arrow=False,arrow_coord=(0.4,30),ratio=None,bbox_to_anchor=(1.1,1.2),use_doublearrow=False,
				linestyles=None,use_text_arrow=False,fps_double_arrow=False,linewidth=None,markersize=None,motparallel_annot=False,
				motrd_annot=False,refcost_annot=False,refdepth_annot=False):
	if linewidth is None:
		linewidth = 2
	if markersize is None:
		markersize = 8
	fig, ax = plt.subplots()
	ax.grid(zorder=0)
	for i in range(len(XX)):
		xx,yy = XX[i],YY[i]
		if yerr is None:
			if linestyles is not None:
				plt.plot(xx, yy, color = color[i], marker = markers[i], 
					linestyle = linestyles[i], 
					label = label[i], 
					linewidth=linewidth, markersize=markersize)
			else:
				plt.plot(xx, yy, color = color[i], marker = markers[i], 
					label = label[i], 
					linewidth=linewidth, markersize=markersize)
		else:
			plt.errorbar(xx, yy, yerr=yerr[i], color = color[i], 
				marker = markers[i], label = label[i], 
				linewidth=linewidth, markersize=markersize)
	plt.xlabel(xlabel, fontsize = lbsize)
	plt.ylabel(ylabel, fontsize = lbsize)
	if xticks is not None:
		if xticklabel is None:
			plt.xticks(xticks,fontsize=lfsize)
		else:
			plt.xticks(xticks,xticklabel,fontsize=lfsize)
	ax.tick_params(axis='both', which='major', labelsize=lbsize)
	if yticks is not None:
		plt.yticks(yticks,fontsize=lbsize)
	if yticklabel is not None:
		ax.set_yticklabels(yticklabel)
	if xlim is not None:
		ax.set_xlim(xlim)
	if ylim is not None:
		ax.set_ylim(ylim)
	if use_arrow:
		ax.text(
		    arrow_coord[0], arrow_coord[1], "Better", ha="center", va="center", rotation=-45, size=lbsize,
		    bbox=dict(boxstyle="larrow,pad=0.3", fc="white", ec="black", lw=2))
	if use_doublearrow:
		plt.axhline(y = YY[0,0], color = color[0], linestyle = '--')
		ax.annotate(text='', xy=(2,YY[0,0]), xytext=(2,YY[0,1]), arrowprops=dict(arrowstyle='<->',lw=2, color = color[0]))
		ax.text(
		    2.5, 25, "76% less time", ha="center", va="center", rotation='vertical', size=lfsize, color = color[0])
		plt.axhline(y = YY[2,0], color = color[2], linestyle = '--')
		ax.annotate(text='', xy=(6,YY[2,0]), xytext=(6,YY[2,5]), arrowprops=dict(arrowstyle='<->',lw=2, color = color[2]))
		ax.text(
		    6.5, 23, "87% less time", ha="center", va="center", rotation='vertical', size=lfsize,color = color[2])
	if fps_double_arrow:
		for i in range(3):
			ax.annotate(text='', xy=(31+i*0.5,YY[3*i,0]), xytext=(31+i*0.5,YY[0+3*i,-1]), arrowprops=dict(arrowstyle='<->',lw=2, color = color[i*3]))
			ax.text(
			    32+i*0.5, (YY[3*i,-1]+YY[i*3,0])/2+i*0.5, f"{YY[3*i,-1]/YY[3*i,0]:.1f}X", ha="center", va="center", rotation='vertical', size=lfsize, color = color[i*3])
	if use_text_arrow:
		ax.annotate('Better speed and\ncoding efficiency trade-off', xy=(XX[2][-1]+1, YY[2,-1]+20),  xycoords='data',
            xytext=(0.25, 0.4), textcoords='axes fraction',
            arrowprops=dict(arrowstyle='->',lw=2),size=lbsize,
            # horizontalalignment='right', verticalalignment='top'
            )
	if motparallel_annot:
		ax.annotate(text="$\downarrow74\%$ for Mc(1080)", xy=(16,YY[2][15]), xytext=((4,5)), arrowprops=dict(arrowstyle='->',lw=2),size=lfsize,fontweight='bold')
		ax.annotate(text="$\downarrow77\%$ for Rc(1080)", xy=(6,YY[7][5]), xytext=((9,0)), arrowprops=dict(arrowstyle='->',lw=2),size=lfsize,fontweight='bold')
	if motrd_annot:
		ax.text(1.,36.5, "Learned codecs:\nHigh coding efficiency", ha="center", va="center", size=lfsize+4,fontweight='bold',color='#00AA88')
	if refcost_annot:
		ax.text(30,900, "One-hop's ref cost increases\nfaster than others", ha="center", va="center", size=lfsize,fontweight='bold',)
	if refdepth_annot:
		ax.text(40.,15, "Chain's ref depth increases\nfaster than others", ha="center", va="center", size=lfsize,fontweight='bold',)
	

	if ncol!=0:
		if ncol is None:
			plt.legend(loc=legloc,fontsize = lfsize)
		else:
			plt.legend(loc=legloc,fontsize = lfsize,ncol=ncol,bbox_to_anchor=bbox_to_anchor)
	
	if ratio is not None:
		xleft, xright = ax.get_xlim()
		ybottom, ytop = ax.get_ylim()
		ax.set_aspect(abs((xright-xleft)/(ybottom-ytop))*ratio)
	# plt.xlim((0.8,3.2))
	# plt.ylim((-40,90))
	plt.tight_layout()
	fig.savefig(path,bbox_inches='tight')
	plt.close()

def bar_plot(avg,std,label,path,color,ylabel,labelsize=24,yticks=None):
	N = len(avg)
	ind = np.arange(N)  # the x locations for the groups
	width = 0.5       # the width of the bars
	fig, ax = plt.subplots()
	ax.grid(zorder=0)
	ax.set_axisbelow(True)
	if std is not None:
		hbar = ax.bar(ind, avg, width, color=color, \
			yerr=std, error_kw=dict(lw=1, capsize=1, capthick=1))
	else:
		hbar = ax.bar(ind, avg, width, color=color, \
			error_kw=dict(lw=1, capsize=1, capthick=1))
	ax.set_ylabel(ylabel, fontsize = labelsize)
	ax.set_xticks(ind,fontsize=labelsize)
	ax.set_xticklabels(label, fontsize = labelsize)
	ax.bar_label(hbar, fmt='%.2f', fontsize = labelsize,fontweight='bold',padding=8)
	if yticks is not None:
		plt.yticks( yticks,fontsize=18 )
	# xleft, xright = ax.get_xlim()
	# ybottom, ytop = ax.get_ylim()
	# ratio = 0.3
	# ax.set_aspect(abs((xright-xleft)/(ybottom-ytop))*ratio)
	plt.tight_layout()
	fig.savefig(path,bbox_inches='tight')
	plt.close()

def hbar_plot(avg,std,label,path,color,xlabel):
	plt.rcdefaults()
	fig, (ax1,ax2) = plt.subplots(1,2,sharey=True)

	y_pos = np.arange(len(avg))
	width = 0.5
	hbars1 = ax1.barh(y_pos, avg, width, color=color, xerr=std, align='center', error_kw=dict(lw=1, capsize=1, capthick=1))
	hbars2 = ax2.barh(y_pos, avg, width, color=color, xerr=std, align='center', error_kw=dict(lw=1, capsize=1, capthick=1))
	
	ax1.set_xlim(0,200)
	ax2.set_xlim(450,500)

	# hide the spines between ax and ax2
	ax1.spines['right'].set_visible(False)
	ax2.spines['left'].set_visible(False)
	ax1.yaxis.tick_left()
	# ax1.tick_params(labelright='off')

	d = .03 # how big to make the diagonal lines in axes coordinates
	# arguments to pass plot, just so we don't keep repeating them
	kwargs = dict(transform=ax1.transAxes, color='r', clip_on=False)
	ax1.plot((1-d,1+d), (-d,+d), **kwargs)
	ax1.plot((1-d,1+d),(1-d,1+d), **kwargs)

	kwargs.update(transform=ax2.transAxes)  # switch to the bottom axes
	ax2.plot((-d,+d), (1-d,1+d), **kwargs)
	ax2.plot((-d,+d), (-d,+d), **kwargs)

	ax1.bar_label(hbars1, fmt='%.2f', fontsize = labelsize_b-8)
	ax2.bar_label(hbars2, fmt='%.2f', fontsize = labelsize_b-8)
	ax1.set_yticks(y_pos, labels=label, fontsize = labelsize_b)
	ax1.invert_yaxis()  

	ax1.set_xticks([])
	ax2.set_xticks([])

	plt.tight_layout()
	fig.text(0.55, 0, xlabel, ha='center', fontsize = labelsize_b-8)
	fig.savefig(path,bbox_inches='tight')


def measurements_to_cdf(latency,epsfile,labels,xticks=None,xticklabel=None,linestyles=linestyles,colors=colors,
                        xlabel='Normalized QoE',ylabel='CDF',ratio=None,lbsize = 18,lfsize = 18,linewidth=4,bbox_to_anchor=(0.5,-.5),
                        loc='upper center',ncol=3):
    # plot cdf
    fig, ax = plt.subplots()
    ax.grid(zorder=0)
    for i,latency_list in enumerate(latency):
        N = len(latency_list)
        cdf_x = np.sort(np.array(latency_list))
        cdf_p = np.array(range(N))/float(N)
        plt.plot(cdf_x, cdf_p, color = colors[i], label = labels[i], linewidth=linewidth, linestyle=linestyles[i])
    plt.xlabel(xlabel, fontsize = lbsize)
    plt.ylabel(ylabel, fontsize = lbsize)
    if xticks is not None:
        plt.xticks(xticks,fontsize=lbsize)
    if xticklabel is not None:
        ax.set_xticklabels(xticklabel)
    if ratio is not None:
        xleft, xright = ax.get_xlim()
        ybottom, ytop = ax.get_ylim()
        ax.set_aspect(abs((xright-xleft)/(ybottom-ytop))*ratio)
    if bbox_to_anchor is not None:
    	plt.legend(loc=loc,fontsize = lfsize,bbox_to_anchor=bbox_to_anchor, fancybox=True,ncol=ncol)
    else:
    	plt.legend(loc=loc,fontsize = lfsize, fancybox=True,ncol=ncol)
    plt.tight_layout()
    fig.savefig(epsfile,bbox_inches='tight')
    plt.close()

def groupedbar(data_mean,data_std,ylabel,path,yticks=None,envs = [2,3,4],colors=colors,
				methods=['Ours','Standalone','Optimal','Ours*','Standalone*','Optimal*'],use_barlabel_x=False,use_barlabe_y=False,
				ncol=3,bbox_to_anchor=(0.46, 1.28),sep=1.,width=0.5,xlabel=None,legloc=None,labelsize=labelsize_b,ylim=None,lfsize=labelsize_b,
				rotation=None,bar_label_dxdy=(-0.3,5),use_realtime_line=False,additional_y=None,ratio=None,motrebuffer_annot=False,):
	fig = plt.figure()
	ax = fig.add_subplot(111)
	num_methods = data_mean.shape[1]
	num_env = data_mean.shape[0]
	center_index = np.arange(1, num_env + 1)*sep
	# colors = ['lightcoral', 'orange', 'yellow', 'palegreen', 'lightskyblue']
	# colors = ['coral', 'orange', 'green', 'cyan', 'blue']

	ax.grid()
	ax.spines['bottom'].set_linewidth(3)
	ax.spines['top'].set_linewidth(3)
	ax.spines['left'].set_linewidth(3)
	ax.spines['right'].set_linewidth(3)
	if additional_y is not None:
		xtick_loc = center_index.tolist() + [4.5]
		envs += ['CPU']
	else:
		xtick_loc = center_index

	if rotation is None:
		plt.xticks(xtick_loc, envs, size=labelsize)
	else:
		plt.xticks(xtick_loc, envs, size=labelsize, rotation=rotation)
	plt.yticks(fontsize=labelsize)
	ax.set_ylabel(ylabel, size=labelsize)
	if xlabel is not None:
		ax.set_xlabel(xlabel, size=labelsize)
	if yticks is not None:
		plt.yticks(yticks,fontsize=labelsize)
	if ylim is not None:
		ax.set_ylim(ylim)
	for i in range(num_methods):
		x_index = center_index + (i - (num_methods - 1) / 2) * width
		hbar=plt.bar(x_index, data_mean[:, i], width=width, linewidth=2,
		        color=colors[i], label=methods[i], hatch=hatches[i], edgecolor='k')
		if data_std is not None:
		    plt.errorbar(x=x_index, y=data_mean[:, i],
		                 yerr=data_std[:, i], fmt='k.', elinewidth=2,capsize=4)
		if use_barlabel_x:
			for k,xdx in enumerate(x_index):
				if data_mean[k,i]>1:
					ax.text(xdx+bar_label_dxdy[0],data_mean[k,i]+bar_label_dxdy[1],f'{data_mean[k,i]:.1f}',fontsize = labelsize, fontweight='bold')
				else:
					ax.text(xdx+bar_label_dxdy[0],data_mean[k,i]+bar_label_dxdy[1],f'{data_mean[k,i]:.2f}',fontsize = labelsize, fontweight='bold')
		if use_barlabe_y and i==1:
			for k,xdx in enumerate(x_index):
				ax.text(xdx-0.02,data_mean[k,i]+.02,f'{data_mean[k,i]:.4f}',fontsize = 18, rotation='vertical',fontweight='bold')
	if additional_y is not None:
		for i in range(additional_y.shape[0]):
			x_index = 4.5 + (i - (additional_y.shape[0] - 1) / 2) * width
			hbar=plt.bar(x_index, additional_y[i], width=width, linewidth=2,
		        color=colors[i+num_methods], label=methods[i+num_methods], hatch=hatches[i+num_methods], edgecolor='k')

	if use_realtime_line:
		plt.axhline(y = 30, color = '#DB1F48', linestyle = '--')
		ax.text(1.5, 120, "Learned codecs:\nLow frame rates", ha="center", va="center", size=lfsize+4,fontweight='bold', rotation='vertical',color='#D62728')
	if motrebuffer_annot:
		ax.text(1.2,0.5, "Learned codecs:\nHigh rebuffer\nand stall rates", ha="center", va="center", rotation='vertical', size=lfsize+6,fontweight='bold',color='#D62728')
		# ax.text(2,.5, "Learned codecs:\nhigh stall rates", ha="center", va="center", size=lfsize,fontweight='bold',color='#e3342f')

	if ratio is not None:
		xleft, xright = ax.get_xlim()
		ybottom, ytop = ax.get_ylim()
		ax.set_aspect(abs((xright-xleft)/(ybottom-ytop))*ratio)
	if ncol>0:
		if legloc is None:
			plt.legend(bbox_to_anchor=bbox_to_anchor, fancybox=True,
			           loc='upper center', ncol=ncol, fontsize=lfsize)
		else:
			plt.legend(fancybox=True,
			           loc=legloc, ncol=ncol, fontsize=lfsize)
	plt.tight_layout()
	fig.savefig(path, bbox_inches='tight')
	plt.close()

def plot_clustered_stacked(dfall, filename, labels=None, horizontal=False, xlabel='', ylabel='',**kwargs):
    """Given a list of dataframes, with identical columns and index, create a clustered stacked bar plot. 
labels is a list of the names of the dataframe, used for the legend
title is a string for the title of the plot
H is the hatch used for identification of the different dataframe"""
    fig = plt.figure()
    n_df = len(dfall)
    n_col = len(dfall[0].columns) 
    n_ind = len(dfall[0].index)
    axe = plt.subplot(111)

    for df in dfall : # for each data frame
        axe = df.plot(kind="bar",
                      linewidth=0,
                      stacked=True,
                      ax=axe,
                      legend=False,
                      grid=False,
                      color=['#DB1F48','#1C4670',],
                      edgecolor='k',
                      **kwargs)  # make bar plots

    h,l = axe.get_legend_handles_labels() # get the handles we want to modify
    for i in range(0, n_df * n_col, n_col): # len(h) = n_col * n_df
        for j, pa in enumerate(h[i:i+n_col]):
            for rect in pa.patches: # for each index
                rect.set_x(rect.get_x() + 1 / float(n_df + 1) * i / float(n_col))
                rect.set_hatch(hatches[i//n_col]) #edited part     
                rect.set_width(1 / float(n_df + 1))

    axe.set_xticks((np.arange(0, 2 * n_ind, 2) + 1 / float(n_df + 1)) / 2.)
    axe.set_xticklabels(df.index, rotation = 0)
    axe.tick_params(axis='both', which='major', labelsize=20)
    axe.set_xlabel(xlabel, size=24)
    axe.set_ylabel(ylabel, size=24)

    # Add invisible data to add another legend
    n=[]        
    for i in range(n_df):
        n.append(axe.bar(0, 0, color="white", hatch=hatches[i],edgecolor='black'))

    n2 = []
    for i,clr in enumerate(['#DB1F48','#1C4670',]):
    	n2.append(axe.bar(0, 0, color=clr))

    if labels is not None:
        if not horizontal:
            # l1 = axe.legend(h[:n_col], l[:n_col], loc=[.01, 0.78], fontsize=18)
            l3 = plt.legend(n2, ['Motion','Residual'], loc=[.01, 0.78], fontsize=18) 
            l2 = plt.legend(n, labels, loc=[.01, 0.47], fontsize=18) 
        else:
            # l1 = axe.legend(h[:n_col], l[:n_col], loc=[.68, 0.78], fontsize=18)
            l3 = axe.legend(n2, ['Enc','Dec'], loc=[.68, 0.78], fontsize=18) 
            l2 = plt.legend(n, labels, loc=[.68, 0.47], fontsize=18) 
    axe.add_artist(l3)
    plt.tight_layout()
    fig.savefig(filename, bbox_inches='tight')
    plt.close()
    return axe


UPSNRs = [[32.543478441762396, 34.573014674724995, 36.19663649696213, 37.28057779941882, 38.72632463985866, 39.22430920219802, 39.87904687051649], 
[32.65380431245734, 34.55438403483038, 36.062224239974356, 37.17589424849748, 37.86222585312255, 38.50796908617734, 39.215505181492624, 40.038787832031474], 
[31.74693045439896, 33.41208141047756, 34.92100008336695, 36.22079029021326, 37.261527250339455, 38.0560033669124, 38.6483168490045], 
[33.07011698223614, 34.53811576959493, 35.80980415825363, 36.87108862935961, 37.72481086704281, 38.402927373196334, 38.884062338780446], 
[32.843874187021704, 34.38099358012745, 35.724521354719116, 36.837054323364086, 37.71883388928005, 38.40001107048202, 38.890123292520926], 
[32.79842881913428, 34.26208116958191, 35.552305886557285, 36.645252529557766, 37.536240949259174, 38.228766637367684, 38.73681622856743], 
[32.75936338379904, 34.18578829179396, 35.46085622951343, 36.518808956746454, 37.36077980942779, 38.02671724671012, 38.53779179423482], 
[32.8636163464793, 34.33908462834049, 35.645658467080324, 36.718912166315356, 37.55216830355542, 38.19651269031453, 38.677899544531996]]
Ubpps = [[0.0635721028971029, 0.09370483266733268, 0.13689532967032966, 0.19788029470529467, 0.5477026098901099, 0.7162948801198801, 0.9466557942057943], 
[0.05500911588411588, 0.08862457542457543, 0.13366452297702297, 0.19711898101898104, 0.272768469030969, 0.39096426073926077, 0.5724937562437562, 0.8423756368631369], 
[0.051151173826173825, 0.08479610389610388, 0.14546853146853148, 0.26021663336663337, 0.47320390859140854, 0.8407709665334665, 1.4137036463536463], 
[0.06028671328671329, 0.09762492507492508, 0.15979454295704296, 0.26925576923076927, 0.46507764735264734, 0.8332161088911089, 1.4514770479520478], 
[0.05758936063936063, 0.09309536713286713, 0.15230112387612385, 0.25873106893106895, 0.44751312437562435, 0.810325024975025, 1.4410407717282716], 
[0.052209752747252744, 0.08867724775224775, 0.15350600649350649, 0.27385037462537465, 0.5003003621378621, 0.9180783216783216, 1.5802436813186813], 
[0.042274475524475524, 0.06967703546453546, 0.11463427822177823, 0.19173451548451548, 0.32591756993006993, 0.5685101148851149, 0.989252072927073], 
[0.04214488011988012, 0.07000197302697303, 0.11528716283716285, 0.19448647602397603, 0.3312023601398601, 0.5897757242757242, 1.0536495129870131]]

colors_tmp = ['#e3342f','#f6993f','#ffed4a','#38c172','#4dc0b5','#3490dc','#6574cd','#9561e2','#f66d9b']
labels_tmp = ['DVC','RLVC','x264f','x264m','x264s','x265f','x265m','x265s']
line_plot(Ubpps,UPSNRs,labels_tmp,colors_tmp,
		'/home/bo/Dropbox/Research/NSDI24Hermes/images/mot_RDtradeoff.eps',
		'Bit Per Pixel','PSNR (dB)',use_arrow=True,arrow_coord=(0.15,39.2),lbsize=24,lfsize=20,ncol=2,bbox_to_anchor=None,motrd_annot=True)


labels_tmp = ['DVC','RLVC','x264f','x264m','x264s','x265f','x265m','x265s']
colors_tmp = ['#e3342f','#f6993f','#ffed4a','#38c172','#4dc0b5','#3490dc','#6574cd','#9561e2','#f66d9b']
for trace in range(1):
	for hw in [1080]:
		meanQoE_all = [];stdQoE_all = []
		for k,metric in enumerate(['rebuffer','stall']):
			datafile = f'/home/bo/Dropbox/Research/NSDI24Hermes/data_novb/{metric}_{trace}_{hw}_1000.data'
			with open(datafile,'r') as f:
				line = f.readlines()[0]
			QoE_matrix = eval(line)
			QoE_matrix = np.array(QoE_matrix)
			print(QoE_matrix.shape)
			# QoE_min,QoE_max = QoE_matrix.min(),QoE_matrix.max()
			# QoE_matrix = (QoE_matrix - QoE_min) / (QoE_max - QoE_min) 
			# measurements_to_cdf(QoE_matrix,f'/home/bo/Dropbox/Research/SIGCOMM23-VC/data_vb/{metric}cdf_{trace}_{hw}.eps',labels_tmp,linestyles=linestyles,
			# 	colors=colors_tmp,bbox_to_anchor=(.14,1.02),lfsize=16,ncol=1)
			meanQoE = QoE_matrix.mean(axis=1)
			stdQoE = QoE_matrix.std(axis=1)
			meanQoE_all += [meanQoE]
			stdQoE_all += [stdQoE]
		meanQoE_all = np.stack(meanQoE_all).reshape(2,9)
		print(meanQoE_all.tolist())
		stdQoE_all = np.stack(stdQoE_all).reshape(2,9)
		meanQoE_all = meanQoE_all[:,1:]
		stdQoE_all = stdQoE_all[:,1:]
		groupedbar(meanQoE_all,stdQoE_all,f'Rebuffer/Stall Rate', 
			f'/home/bo/Dropbox/Research/NSDI24Hermes/images/mot_allmetric.eps',methods=labels_tmp,colors=colors_tmp,
			envs=['Rebuffer','Stall'],ncol=1,sep=1,width=0.1,labelsize=18,lfsize=16,bbox_to_anchor=(.83,1.0),xlabel='',ratio=.7,motrebuffer_annot=True)

# motivation

y = [0.0382, 0.05810000000000001, 0.004889435564435564, 0.005005499857285572, 0.005083814399885828, 0.0074054160125588695, 0.0058336038961038965, 0.006322325888397318] 
y = 1/np.array(y).reshape(-1,1)
# Intel(R) Core(TM) i7-9700K CPU @ 3.60GHz
groupedbar(y,None,'Frame Rate (fps)', 
	'/home/bo/Dropbox/Research/NSDI24Hermes/images/mot_FPS.eps',methods=['QoE'],colors=['#4f646f'],labelsize=24,ylim=(0,230),lfsize=20,
	envs=labels_tmp,ncol=0,rotation=45,use_realtime_line=True,bar_label_dxdy=(-0.4,5),yticks=range(0,250,30))

exit(0)


y = [[0.014343031600003543, 0.01041380439999955, 0.010020919000000579, 0.0099386924749993, 0.009637096180000526, 0.009600869550000841, 0.01225261787142894, 0.010805716924999587, 0.013351780355555497, 0.01012761901000033, 0.009969255518181667, 0.007719925508333367, 0.007699777169230733, 0.007648280071428612, 0.010007865553333205, 0.008840933706250099],
[0.006625925800000232, 0.006346201299999165, 0.006341402133332015, 0.006342856949999032, 0.006327184579999994, 0.006357724933333013, 0.006347319628571313, 0.006374761762499759, 0.006373157866666664, 0.0062588391100001665, 0.006265954209090875, 0.006284894324999849, 0.006266073861538556, 0.006278202685714161, 0.006285975300000171, 0.006274069393749926],
[0.009788564599995197, 0.0056723488500011856, 0.004542434600000434, 0.003942178399999818, 0.0034641688600004273, 0.0033191265666668336, 0.0031489199285715586, 0.0030690584375001606, 0.002980760222222519, 0.002853297139999995, 0.002858350881818565, 0.0028115879500001974, 0.0028135829076924995, 0.0027622289928570707, 0.0026007485066668326, 0.0025161357312498468],
[0.0023812532000022204, 0.0012252736000021968, 0.0011258689000006447, 0.0010912724500002468, 0.0010747372999992421, 0.0010866475833334259, 0.001095822742857016, 0.001089503850000284, 0.001083051966666441, 0.0010845429599999079, 0.0010884973272724933, 0.0010837969333332845, 0.0010875969076922642, 0.0010888162785716662, 0.0010900460866666132, 0.0010966444687500853],
[0.009234742901753634, 0.006466144445585087, 0.006408295900716136, 0.006306733522797004, 0.006329124320764094, 0.006253925200629358, 0.006255993928893337, 0.006229863688349724, 0.006236946655230389, 0.006252231739927084, 0.006256915863857351, 0.006183018575150831, 0.0061840860611902405, 0.006170267007213884, 0.007941721680108458, 0.006696910068421857],
[0.003977414895780384, 0.0033896182489115746, 0.003325708598519365, 0.003204127147910185, 0.0032117165997624397, 0.0031966645328793675, 0.0031817725992628505, 0.0031854681248660198, 0.0031845097223089803, 0.0031887905206531286, 0.0031816045086915518, 0.0031876937408621114, 0.0031903283464579054, 0.0031941108355697774, 0.0033302903803996745, 0.0033120781437901313],
[0.0036982840043492614, 0.0037547587999142706, 0.0028550525661557914, 0.002246458173613064, 0.0020834707003086804, 0.0018473271668578187, 0.001775100128725171, 0.001628735636768397, 0.0016182308550924062, 0.0017877266206778586, 0.0017596907733770256, 0.0015271638665581122, 0.0015234037383029667, 0.0014682741785821106, 0.0016838036671591302, 0.0016311438121192623],
[0.0016299561015330256, 0.0008188631443772465, 0.0005516854658101995, 0.0005071888241218403, 0.0005029045604169368, 0.0004986089673669388, 0.0008356139579388713, 0.0009494408746832051, 0.0008908048336808052, 0.0009065217094030232, 0.0009322019357403572, 0.0013202978918949763, 0.001250024730912768, 0.0011961570849442587, 0.002184627839984993, 0.0020987257375963964],]
y = np.array(y)*1000
# y = y[[1,2,3,5,6,7,]]
# print((y.min(axis=1)/y.max(axis=1)).tolist())
# print((y.min(axis=1)-y.max(axis=1)).tolist())
# print(np.argmin(y,axis=1))


x = [range(1,y.shape[1]+1) for _ in range(y.shape[0])]

colors_tmp = ['#e3342f','#f6993f','#ffed4a','#38c172','#4dc0b5','#3490dc','#6574cd','#9561e2','#f66d9b']
line_plot(x,y,['ME(1080)','MC(1080)','Mc(1080)','Rc(1080)','ME(2080)','MC(2080)','Mc(2080)','Rc(2080)'],colors_tmp,
		'/home/bo/Dropbox/Research/NSDI24Hermes/images/mot_parallel.eps',
		'Batch Size','Proc. Time (ms)',ncol=1,legloc='best',lbsize=20,lfsize=14,bbox_to_anchor=(0.68,1),xticks=range(0,26,5),
		motparallel_annot=True,ratio=0.45)
exit(0)
SPSNRs = [
[30.91,32.62,33.89,34.57],
[30.94,32.58,33.87,34.60],
[30.63,32.17,33.52,34.39],
[30.17,31.72,33.12,34.07],
[29.72,31.29,32.74,33.76],
]
Sbpps = [
[0.23,0.36,0.54,0.74],
[0.21,0.30,0.44,0.61],
[0.12,0.18,0.266,0.37],
[0.11,0.16,0.22,0.31],
[0.10,0.15,0.21,0.30],
]
sc_labels = ['subGOP=1','subGOP=2','subGOP=6','subGOP=14','subGOP=30']
line_plot(Sbpps,SPSNRs,sc_labels,colors,
		'/home/bo/Dropbox/Research/NSDI24Hermes/images/scalability_rdtradeoff.eps',
		'Bit Per Pixel','PSNR (dB)',use_arrow=True,arrow_coord=(0.15,34),lbsize=24,lfsize=18,
		xticks=[0.1,0.2,.3,.4,.5,.6,.7],yticks=range(30,35))
exit(0)
########################ABLATION####################################
# UVG
ab_labels = ['Default','w/o ST','Chain','One-hop']
bpps = [[0.12,0.18,0.266,0.37],
		[0.12,0.20,0.30,0.41],
        [0.10,0.15,0.23,0.33],
		[0.11,0.17,0.27,0.41],
		]
PSNRs = [[30.63,32.17,33.52,34.39],
		[29.83,31.25,32.74,34.05],
        [29.33,31.15,32.76,33.74],
		[29.77,31.62,32.99,33.92],
		]
line_plot(bpps,PSNRs,ab_labels,colors,
		'/home/bo/Dropbox/Research/NSDI24Hermes/images/ablation_rdtradeoff.eps',
		'Bit Per Pixel','PSNR (dB)',use_arrow=True,arrow_coord=(0.13,33.5),lbsize=28,lfsize=24,
		xticks=[.1,.2,.3,.4],yticks=range(30,35))

ab_labels = ['Default','w/o ST','Chain','One-hop']
fps_avg_list = [32.21, 32.63, 16.17, 32.98]
bar_plot(fps_avg_list,None,ab_labels,
		'/home/bo/Dropbox/Research/NSDI24Hermes/images/ablation_speed.eps',
		'#4f646f','Frame Rate (fps)',yticks=range(0,45,5),labelsize=28)
exit(0)
d = np.arange(1,6)
chain_cost = 2**(d+1)-2
oh_cost = (1+chain_cost)/2*chain_cost
bt_cost = np.array([3,11,31,79,191]) #prev*2+1+2^d
allcost = np.stack((chain_cost,oh_cost,bt_cost))
alldepth = [chain_cost,[1 for _ in range(5)],d]
x = [2**(d+1)-2 for _ in range(3)]
line_plot(x,allcost,['Chain','One-hop','Binary'],colors,
		'/home/bo/Dropbox/Research/NSDI24Hermes/images/graph_analysis_cost.eps',
		'#Frame','Reference Cost',ncol=1,legloc='upper left',lbsize=32,
		lfsize=20,bbox_to_anchor=None,linewidth=4,markersize=8,refcost_annot=True)
line_plot(x,alldepth,['Chain','One-hop','Binary'],colors,
		'/home/bo/Dropbox/Research/NSDI24Hermes/images/graph_analysis_depth.eps',
		'#Frame','Reference Depth',ncol=1,legloc='upper left',lbsize=32,lfsize=20,
		bbox_to_anchor=None,linewidth=4,markersize=8,refdepth_annot=True)
exit(0)
##############################Overall#############################
# 16543747 bps=15.8Mbps
# 4074145 mbps=3.9Mbps
labels_tmp = ['Ours','DVC','RLVC','x264f','x264m','x264s','x265f','x265m','x265s']
colors_tmp = ['#e3342f','#f6993f','#ffed4a','#38c172','#4dc0b5','#3490dc','#6574cd','#9561e2','#f66d9b']
metric_list = []
for trace in range(2):
	for k,metric in enumerate(['QoE','quality','rebuffer']):
		meanQoE_all = [];stdQoE_all = []
		for hw in [1080,2080,3090]:
			datafile = f'/home/bo/Dropbox/Research/SIGCOMM23-VC/data_vb/{metric}_{trace}_{hw}_1000.data'
			with open(datafile,'r') as f:
				line = f.readlines()[0]
			QoE_matrix = eval(line)
			QoE_matrix = np.array(QoE_matrix)
			QoE_min,QoE_max = QoE_matrix.min(),QoE_matrix.max()
			QoE_matrix = (QoE_matrix - QoE_min) / (QoE_max - QoE_min) 
			measurements_to_cdf(QoE_matrix,f'/home/bo/Dropbox/Research/SIGCOMM23-VC/data_vb/{metric}cdf_{trace}_{hw}.eps',labels_tmp,linestyles=linestyles,
				colors=colors_tmp,bbox_to_anchor=(.14,1.02),lfsize=16,ncol=1,lbsize=24)
			meanQoE = QoE_matrix.mean(axis=1)
			stdQoE = QoE_matrix.std(axis=1)
			meanQoE_all += [meanQoE]
			stdQoE_all += [stdQoE]
		meanQoE_all = np.stack(meanQoE_all).reshape(3,9)
		# print(meanQoE_all.tolist())
		stdQoE_all = np.stack(stdQoE_all).reshape(3,9)
		names = ['QoE','Quality','Rebuffer Rate']
		if k == 0:
			ncol = 1
			labelsize=18
		else:
			labelsize=24
			ncol = 0
		groupedbar(meanQoE_all,stdQoE_all,f'Normalized {names[k]}', 
			f'/home/bo/Dropbox/Research/SIGCOMM23-VC/data_vb/{metric}mean_{trace}.eps',methods=labels_tmp,colors=colors_tmp,
			envs=['1080','2080','3090'],ncol=ncol,sep=1,width=0.1,labelsize=labelsize,lfsize=16,bbox_to_anchor=(1.22,1.05),xlabel='Hardware',ratio=.7)
		if metric == 'QoE':
			for line in meanQoE_all.tolist():
				ours,t_top1,l_top1 = line[0],max(line[1:3]),max(line[3:])
				m1,m2=(ours - t_top1)/t_top1,(ours - l_top1)/l_top1
				metric_list += [[m1,m2]]
metric_list = np.array(metric_list)
print(metric_list)
print(metric_list.mean(axis=0))
print(metric_list[:3].mean(axis=0))
print(metric_list[3:].mean(axis=0))
exit(0)

# [0.101,0.088],[0.053,0.04731],[0.061,0.04164]
ratio = [[[0.088/0.101,1],[19.5/29.7,1],[32.4/46,1]],
[[0.047/0.053,1],[28/39,1],[40.2/51.9,1]],
[[0.042/0.061,1],[52.6/64.4,1],[63.2/79.0,1]]]
dect = [
[[0.0310]*2,[0.0195]*2,[0.010]*2,],
[[0.0382]*2,[0.028]*2,[0.01]*2,],
[[0.0581]*2,[0.0526]*2,[0.012]*2]]
# dect = [[[0.0310]*2,[0.0382]*2,[0.0581]*2,],
# [[0.0195]*2,[0.028]*2,[0.0526]*2,],
# [[0.010]*2,[0.01]*2,[0.012]*2,],]
ratio = np.flip(np.array(ratio),axis=1)
dect=np.array(dect)
encdec = (ratio*dect)*1000

indices = ["GTX 1080 Ti","RTX 2080 Ti", "RTX 3090 Ti"]
columns = ["Enc", "Dec"]
df1 = pd.DataFrame(encdec[0],
                   index=indices,
                   columns=columns)
df2 = pd.DataFrame(encdec[1],
                   index=indices,
                   columns=columns)
df3 = pd.DataFrame(encdec[2],
                   index=indices,
                   columns=columns)

plot_clustered_stacked([df1, df2, df3],'/home/bo/Dropbox/Research/SIGCOMM23-VC/images/encdec.eps',labels=['Ours','DVC','RLVC'],
	xlabel='Hardware',ylabel='Millisecond',horizontal=True)

bit_dist = [0.025, 0.078,
0.033, 0.106,
0.045, 0.150,
0.063, 0.217,
0.026, 0.023,
0.034, 0.040,
0.046, 0.063,
0.068, 0.100,
0.016, 0.019,
0.025, 0.031,
0.034, 0.050,
0.050, 0.081]
bit_dist = np.array(bit_dist).reshape(12,2)

df1 = pd.DataFrame(bit_dist[:4],
                   index=["256", "512",'1024','2048'],
                   columns=["Motion", "Residual"])
df2 = pd.DataFrame(bit_dist[4:8],
                   index=["256", "512",'1024','2048'],
                   columns=["Motion", "Residual"])
df3 = pd.DataFrame(bit_dist[8:],
                   index=["256", "512",'1024','2048'],
                   columns=["Motion", "Residual"])

plot_clustered_stacked([df1, df2, df3],'/home/bo/Dropbox/Research/SIGCOMM23-VC/images/bits_dist.eps',labels=['Ours','DVC','RLVC'],xlabel='$\lambda$',ylabel='Bit per pixel')
exit(0)

y = [[0.0310,0.0382,0.0581,],
[0.0195,0.028,0.0526,],
[0.010,0.01,0.012,],]

y = 1/np.array(y)
labels_tmp = ['Ours','DVC','RLVC','x264f','x264m','x264s','x265f','x265m','x265s']
additional_y = [0.004889435564435564, 0.005005499857285572, 0.005083814399885828, 
0.0074054160125588695, 0.0058336038961038965, 0.006322325888397318]
additional_y = 1/np.array(additional_y)
colors_tmp = ['#e3342f','#f6993f','#ffed4a','#38c172','#4dc0b5','#3490dc','#6574cd','#9561e2','#f66d9b']

groupedbar(y,None,'Frame Rate (fps)', 
	'/home/bo/Dropbox/Research/SIGCOMM23-VC/images/FPS_all.eps',methods=labels_tmp,colors=colors_tmp,
	envs=['1080','2080','3090'],ncol=1,sep=1,width=0.3,labelsize=24,lfsize=16,yticks=range(0,240,30),
	additional_y=additional_y,bbox_to_anchor=(.15,1.1),xlabel='Hardware')

# RD tradeoff all
x640960_PSNR = [[33.916125480707116, 35.48593550438171, 37.016464507544086, 38.199682581079344, 39.118539617969084, 39.627869858965646, 40.20787336157038], 
[32.543478441762396, 34.573014674724995, 36.19663649696213, 37.28057779941882, 38.58632463985866, 39.22430920219802, 39.87904687051649], 
[32.65380431245734, 34.55438403483038, 36.062224239974356, 37.17589424849748, 37.86222585312255, 38.50796908617734, 39.215505181492624, 40.038787832031474], 
[31.74693045439896, 33.41208141047756, 34.92100008336695, 36.22079029021326, 37.261527250339455, 38.0560033669124, 38.6483168490045], 
[33.07011698223614, 34.53811576959493, 35.80980415825363, 36.87108862935961, 37.72481086704281, 38.402927373196334, 38.884062338780446], 
[32.843874187021704, 34.38099358012745, 35.724521354719116, 36.837054323364086, 37.71883388928005, 38.40001107048202, 38.890123292520926], 
[32.79842881913428, 34.26208116958191, 35.552305886557285, 36.645252529557766, 37.536240949259174, 38.228766637367684, 38.73681622856743], 
[32.75936338379904, 34.18578829179396, 35.46085622951343, 36.518808956746454, 37.36077980942779, 38.02671724671012, 38.53779179423482], 
[32.8636163464793, 34.33908462834049, 35.645658467080324, 36.718912166315356, 37.55216830355542, 38.19651269031453, 38.677899544531996]]
x640960_bpp = [[0.09785748001998001, 0.1369725024975025, 0.19493502747252747, 0.28089705294705297, 0.3879853021978022, 0.5577062437562439, 0.7615622627372628], 
[0.0635721028971029, 0.09370483266733268, 0.13689532967032966, 0.19788029470529467, 0.5477026098901099, 0.7162948801198801, 0.9466557942057943], 
[0.05500911588411588, 0.08862457542457543, 0.13366452297702297, 0.19711898101898104, 0.272768469030969, 0.39096426073926077, 0.5724937562437562, 0.8423756368631369], 
[0.051151173826173825, 0.08479610389610388, 0.14546853146853148, 0.26021663336663337, 0.47320390859140854, 0.8407709665334665, 1.4137036463536463], 
[0.06028671328671329, 0.09762492507492508, 0.15979454295704296, 0.26925576923076927, 0.46507764735264734, 0.8332161088911089, 1.4514770479520478], 
[0.05758936063936063, 0.09309536713286713, 0.15230112387612385, 0.25873106893106895, 0.44751312437562435, 0.810325024975025, 1.4410407717282716], 
[0.052209752747252744, 0.08867724775224775, 0.15350600649350649, 0.27385037462537465, 0.5003003621378621, 0.9180783216783216, 1.5802436813186813], 
[0.042274475524475524, 0.06967703546453546, 0.11463427822177823, 0.19173451548451548, 0.32591756993006993, 0.5685101148851149, 0.989252072927073], 
[0.04214488011988012, 0.07000197302697303, 0.11528716283716285, 0.19448647602397603, 0.3312023601398601, 0.5897757242757242, 1.0536495129870131]]
labels_tmp = ['Ours','DVC','RLVC','x264f','x264m','x264s','x265f','x265m','x265s']
colors_tmp = ['#e3342f','#f6993f','#ffed4a','#38c172','#4dc0b5','#3490dc','#6574cd','#9561e2','#f66d9b']
line_plot(x640960_bpp,x640960_PSNR,labels_tmp,colors_tmp,
		'/home/bo/Dropbox/Research/SIGCOMM23-VC/images/RD_tradeoff.eps',
		'Bit Per Pixel','PSNR (dB)',markers=markers,ncol=2,ratio=None,bbox_to_anchor=(1,.1),legloc='lower right',lbsize=24,lfsize=16,
		use_arrow=True,arrow_coord=(0.15,39))
exit(0)

labels_tmp = ['Ours','DVC','RLVC','x264f','x264m','x264s','x265f','x265m','x265s']
colors_tmp = ['#e3342f','#f6993f','#ffed4a','#38c172','#4dc0b5','#3490dc','#6574cd','#9561e2','#f66d9b']
for k,metric in enumerate(['QoE','quality','rebuffer']):
	meanQoE_all = [];stdQoE_all = []
	for trace in range(2):
		hw = 1080

		datafile = f'/home/bo/Dropbox/Research/SIGCOMM23-VC/data_novb/{metric}_{trace}_{hw}_1000.data'
		with open(datafile,'r') as f:
			line = f.readlines()[0]
		QoE_matrix = eval(line)
		QoE_matrix = np.array(QoE_matrix)
		QoE_min,QoE_max = QoE_matrix.min(),QoE_matrix.max()
		QoE_matrix = (QoE_matrix - QoE_min) / (QoE_max - QoE_min) 
		# measurements_to_cdf(QoE_matrix,f'/home/bo/Dropbox/Research/SIGCOMM23-VC/data/{metric}cdf_{trace}_{hw}.eps',labels_tmp,linestyles=linestyles,
		# 	colors=colors_tmp,bbox_to_anchor=(.14,1.02),lfsize=16,ncol=1)
		meanQoE = QoE_matrix.mean(axis=1)
		stdQoE = QoE_matrix.std(axis=1)
		meanQoE_all += [meanQoE]
		stdQoE_all += [stdQoE]

	meanQoE_all = np.stack(meanQoE_all).reshape(2,9)
	stdQoE_all = np.stack(stdQoE_all).reshape(2,9)
	names = ['QoE','Quality','Rebuffer Rate']
	if k == 0:
		ncol = 1;labelsize=18
	else:
		ncol = 0;labelsize=24
	groupedbar(meanQoE_all,stdQoE_all,f'Normalized {names[k]}', 
		f'/home/bo/Dropbox/Research/SIGCOMM23-VC/data_novb/{metric}mean_cmp.eps',methods=labels_tmp,colors=colors_tmp,
		envs=['Limited BW','Adequate BW'],ncol=ncol,sep=1,width=0.1,labelsize=labelsize,lfsize=16,bbox_to_anchor=(1.22,1.05),xlabel='',ratio=.7)
exit(0)

#######################ERROR PROP########################
eplabels = ['Ours','DVC','RLVC'] # UVG,r=2048
frame_loc = [[i for i in range(7)] for _ in range(len(eplabels))]
DVC_error = [
[29.17373275756836, 29.27086639404297, 29.370689392089844, 29.497406005859375, 29.661972045898438, 29.852237701416016, 30.150089263916016, 29.852378845214844, 29.661556243896484, 29.503952026367188, 29.374088287353516, 29.260000228881836, 29.161962509155273],
[30.87851333618164, 30.991844177246094, 31.11360740661621, 31.27014923095703, 31.462120056152344, 31.68387794494629, 32.09651565551758, 31.678407669067383, 31.453895568847656, 31.26244354248047, 31.11084747314453, 30.96697235107422, 30.851476669311523],
[32.132972717285156, 32.243431091308594, 32.35715866088867, 32.50340270996094, 32.68071746826172, 32.86759948730469, 33.17623519897461, 32.866546630859375, 32.67479705810547, 32.504638671875, 32.3599967956543, 32.226200103759766, 32.11112594604492],
[32.98991012573242, 33.08746337890625, 33.17982864379883, 33.293479919433594, 33.42365646362305, 33.544105529785156, 33.5637092590332, 33.54086685180664, 33.418758392333984, 33.292877197265625, 33.18037414550781, 33.075035095214844, 32.984283447265625],
]
RLVC_error = [
[28.934640884399414, 29.0654354095459, 29.188518524169922, 29.363454818725586, 29.605087280273438, 30.001672744750977, 30.150089263916016, 29.993770599365234, 29.60120391845703, 29.366622924804688, 29.19466209411621, 29.043128967285156, 28.91464614868164],
[30.781314849853516, 30.918954849243164, 31.047901153564453, 31.23015785217285, 31.494022369384766, 31.950214385986328, 32.09651565551758, 31.95067596435547, 31.49615478515625, 31.236337661743164, 31.052120208740234, 30.89519691467285, 30.753807067871094],
[32.05003356933594, 32.206790924072266, 32.35562515258789, 32.55833435058594, 32.83184051513672, 33.269229888916016, 33.17623519897461, 33.277217864990234, 32.842647552490234, 32.578739166259766, 32.3740234375, 32.1959228515625, 32.042484283447266],
[32.94842529296875, 33.0999755859375, 33.23988723754883, 33.43804168701172, 33.688114166259766, 34.05646896362305, 33.5637092590332, 34.05782699584961, 33.69127655029297, 33.450496673583984, 33.25787353515625, 33.094661712646484, 32.95338439941406],
]
ELVC_error = [
[30.324174880981445, 30.538787841796875, 30.67068862915039, 30.49388313293457, 30.715848922729492, 31.25832176208496, 30.150089263916016, 31.260454177856445, 30.7042293548584, 30.511245727539062, 30.683881759643555, 30.523727416992188, 30.34703254699707],
[31.795574188232422, 32.01017379760742, 32.13482666015625, 32.016048431396484, 32.25210189819336, 32.848426818847656, 32.09651565551758, 32.85036849975586, 32.24248123168945, 32.039222717285156, 32.14407730102539, 31.9993953704834, 31.81879997253418],
[33.16758728027344, 33.39623260498047, 33.38203430175781, 33.413753509521484, 33.68014144897461, 34.21955108642578, 33.17623519897461, 34.22688674926758, 33.68741989135742, 33.44963455200195, 33.401241302490234, 33.39918518066406, 33.20851516723633],
[34.112457275390625, 34.34897232055664, 34.174808502197266, 34.358848571777344, 34.64569854736328, 35.04032516479492, 33.5637092590332, 35.05060958862305, 34.66664505004883, 34.40544891357422, 34.20201110839844, 34.366241455078125, 34.17375183105469],
]
ytick_list = [range(29,32),range(31,34),range(32,35),range(33,36)]
bboxes = [(.5,.45),(.6,.55),(.6,.55),(.6,.35)]
for i in range(4):
    PSNRs = [ELVC_error[i],DVC_error[i],RLVC_error[i]]
    ylabel = 'PSNR (dB)' 
    legloc = 'best'
    PSNRs = np.array(PSNRs)
    PSNRs = (np.flip(PSNRs[:,:7],axis=1) + PSNRs[:,6:])/2
    qoe_mean,qoe_std = PSNRs[:,1:].mean(axis=1),PSNRs[:,1:].std(axis=1)
    ncol = 1 
    line_plot(frame_loc,PSNRs,eplabels,colors,
            f'/home/bo/Dropbox/Research/SIGCOMM23-VC/images/error_prop_{i}.eps',
            'Frame Location',ylabel,xticks=range(7),xticklabel=['I']+[f'P{i}' for i in range(1,7)],yticks=ytick_list[i],lbsize=28,lfsize=22,ncol=ncol,linewidth=4,
           	legloc=legloc,bbox_to_anchor=bboxes[i])
exit(0)

######################SCALABILITY##########################
decompt =[ [0.02196,0.01354,0.0100,0.00785,0.00689],
[0.014,0.011,0.010,0.009,0.009],
[0.013,0.012,0.012,0.012,0.012],
[0.03416528925619835, 0.02003305785123967, 0.0195, 0.01668595041322314, 0.0161900826446281],
[0.03349720670391061, 0.025944134078212295, 0.028, 0.026748603351955308, 0.026837988826815644],
[0.057956135770234986, 0.060977545691906006, 0.0526, 0.053080678851174935, 0.05349268929503916],
[0.060496067755595885, 0.04007614467488227, 0.03473126682295737, 0.031039031582214632, 0.030088761847449977], 
[0.04193311667889715, 0.039980009995002494, 0.0388651379712398, 0.038204393505253106, 0.03818615751789976], 
[0.04637143519591931, 0.05238344683080147, 0.05676979846721544, 0.058114194391980234, 0.05871128724497285],]
# decompt =[ [0.01354,0.0100,0.00785,0.00689],
# [0.011,0.010,0.009,0.009],
# [0.012,0.012,0.012,0.012],
# [0.02003305785123967, 0.0195, 0.01668595041322314, 0.0161900826446281],
# [0.025944134078212295, 0.028, 0.026748603351955308, 0.026837988826815644],
# [0.060977545691906006, 0.0526, 0.053080678851174935, 0.05349268929503916],
# [0.04007614467488227, 0.03473126682295737, 0.031039031582214632, 0.030088761847449977], 
# [0.039980009995002494, 0.0388651379712398, 0.038204393505253106, 0.03818615751789976], 
# [0.05238344683080147, 0.05676979846721544, 0.058114194391980234, 0.05871128724497285],]
decompt = 1/np.array(decompt)
# motivation show duration
scalability_labels = ['Ours (3090)','DVC (3090)','RLVC (3090)','Ours (2080)','DVC (2080)','RLVC (2080)','Ours (1080)','DVC (1080)','RLVC (1080)']
show_indices = [0,1,5,13,29] # 1,2,6,14,30
GOP_size = [[(i+1) for i in show_indices] for _ in range(len(scalability_labels))]
colors_tmp = ['#e3342f','#f6993f','#ffed4a','#38c172','#4dc0b5','#3490dc','#6574cd','#9561e2','#f66d9b']
line_plot(GOP_size,decompt,scalability_labels,colors_tmp,
		'/home/bo/Dropbox/Research/SIGCOMM23-VC/images/scalability_fps.eps',
		'Capacity (#Frame)','Frame Rate (fps)',ncol=1,legloc='center right',bbox_to_anchor=(1.2,.5),lbsize=18,lfsize=12,ratio=.6,
		xticks=range(0,41,5),yticks=range(0,151,30),linestyles=linestyles,fps_double_arrow=True)#(0.45,-.16)
exit(0)

datafile = f'/home/bo/Dropbox/Research/SIGCOMM23-VC/images/QoE_0_1080_999.data'
with open(datafile,'r') as f:
	line = f.readlines()[0]
QoE_matrix = eval(line)
QoE_matrix = np.array(QoE_matrix)
QoE_min,QoE_max = QoE_matrix.min(),QoE_matrix.max()

y = [34.981735761479754, 33.06845540139495, 34.70190373585274, 35.411025852453434, 35.41881587778906, 35.207934780186314, 35.61876831087406, 35.76696244352575] 
yerr = [0.6939123489018372, 0.6456513214873756, 0.6517857008913301, 0.5864919879466348, 0.6076016211454529, 0.5619422880146273, 0.5154889680568497, 0.5192746802378674] 
y = np.array(y).reshape(-1,1);yerr = np.array(yerr).reshape(-1,1)
y = (y - QoE_min) / (QoE_max - QoE_min)
yerr /= (QoE_max - QoE_min)
groupedbar(y,yerr,'Normalized QoE', 
	'/home/bo/Dropbox/Research/NSDI24Hermes/images/mot_QoEmean.eps',methods=['QoE'],colors=['#4f646f'],
	envs=labels_tmp,ncol=0,labelsize=24,ylim=(0,1),rotation=45)

labels_tmp = ['DVC','RLVC','x264f','x264m','x264s','x265f','x265m','x265s']
y = [9.40291382e-01, 2.99550380e+00, 2.88042785e-03, 4.20175081e-03,3.68101004e-03, 3.08573793e-03, 2.47046928e-03, 2.46554348e-03] 
yerr = [0.07193951, 0.09499966, 0.00655925, 0.01298857, 0.01017801, 0.00530592,0.00158061, 0.00118021]
y = np.array(y).reshape(-1,1);yerr = np.array(yerr).reshape(-1,1)
groupedbar(y,yerr,'Rebuffer Rate', 
	'/home/bo/Dropbox/Research/NSDI24Hermes/images/mot_rebuffer.eps',methods=['QoE'],colors=['#4f646f'],
	envs=labels_tmp,ncol=0,labelsize=24,rotation=45)