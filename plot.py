#!/usr/bin/python

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import os
lfsize = 18
labelsize = 24
linewidth = 4
mksize = 4
plt.rcParams['xtick.labelsize'] = 20
plt.rcParams['ytick.labelsize'] = 20
plt.rcParams["font.family"] = "Times New Roman"

colors = ['#D00C0E','#E09C1A','#08A720','#86A8E7','#9D5FFB','#D65780']
labels = ['H.264','H.265','DVC','RLVC','LSVC']
markers = ['p','s','o','>','v','^']

def line_plot(XX,YY,labels,path,xlabel,ylabel,xticks=None):
	fig, ax = plt.subplots()
	ax.grid(zorder=0)
	for i in range(len(XX)):
		xx,yy = XX[i],YY[i]
		plt.plot(xx, yy, color = colors[i], marker = markers[i], label = labels[i], linewidth=2)
	plt.xlabel(xlabel, fontsize = labelsize)
	plt.ylabel(ylabel, fontsize = labelsize)
	if xticks is not None:
		plt.xticks( xticks )
	plt.tight_layout()
	plt.legend(loc='best',fontsize = lfsize)
	# plt.xlim((0.8,3.2))
	# plt.ylim((-40,90))
	plt.tight_layout()
	fig.savefig(path,bbox_inches='tight')

bpps = [[0.12,0.20,0.33,0.54],
		[0.14,0.24,0.40,0.67],
		[0.08,0.12,0.19,0.27],
		[0.15,0.10,0.16,0.22],
		[0.102,0.174,0.264,0.3889]
		]
PSNRs = [[30.58,32.26,33.75,34.97],
		[31.53,33.05,34.33,35.36],
		[29.52,31.30,32.52,33.28],
		[28.91,30.89,32.08,32.74],
		[28.84,30.41,31.46,32.09]
		]
line_plot(bpps,PSNRs,labels,
		'/home/bo/Dropbox/Research/SIGCOMM22/images/rate-distortion-UVG.eps',
		'bpp','PSNR (dB)')

bpps = [[0.14,0.23,0.38,0.63],
		[0.16,0.26,0.43,0.76],
		[0.09,0.15,0.22,0.31],
		[0.2,0.21,0.23,0.31],
		[0.17,0.24,0.32,0.43]
		]
PSNRs = [[30.71,32.42,33.95,35.23],
		[31.56,33.16,34.52,35.61],
		[29.98,31.72,32.96,33.73],
		[29.65,31.45,31.84,32.46],
		[30.1,31.64,32.66,33.44]
		]

line_plot(bpps,PSNRs,labels,
		'/home/bo/Dropbox/Research/SIGCOMM22/images/rate-distortion-MCL.eps',
		'bpp','PSNR (dB)')

bpps = [[0.09,0.14,0.23,0.4],
		[0.1,0.17,0.28,0.47],
		[0.06,0.1,0.15,0.22],
		[],
		[]
		]
PSNRs = [[31.10,32.67,34,34.98],
		[32.19,33.57,34.62,35.35],
		[30.28,32.26,33.52,34.27],
		[],
		[]
		]

line_plot(bpps,PSNRs,labels,
		'/home/bo/Dropbox/Research/SIGCOMM22/images/rate-distortion-Xiph.eps',
		'bpp','PSNR (dB)')

bpps = [[0.11,0.18,0.29,0.49],
		[0.13,0.21,0.35,0.57],
		[0.08,0.12,0.18,0.25],
		[],
		[]
		]
PSNRs = [[30.79,32.35,33.77,34.85],
		[31.76,33.21,34.36,35.19],
		[30.82,32.45,33.5,34.11],
		[],
		[]
		]

line_plot(bpps,PSNRs,labels,
		'/home/bo/Dropbox/Research/SIGCOMM22/images/rate-distortion-Xiph2.eps',
		'bpp','PSNR (dB)')

ab_labels = ['Base','C64','C128','Recurrent','Detach','Linear']
bpps = [[0.102,0.174,0.264,0.3889],
		[0.418],
		[0.123,0.181,0.284,0.3925],
		[0.25],
		[],
		[]
		]
PSNRs = [[28.84,30.41,31.46,32.09],
		[30.93],
		[28.98,30.54,31.54,32.24],
		[30.83],
		[],
		[]
		]
line_plot(bpps,PSNRs,ab_labels,
		'/home/bo/Dropbox/Research/SIGCOMM22/images/ablation-UVG.eps',
		'bpp','PSNR (dB)')

# 96
# [0.053132872000105635, 0.07760241199980555, 0.10680426199996873, 0.1364419829999406, 0.16576214699989578, 0.19565956099995674, 0.24735311800009185, 0.2696788140001445, 0.30823042800011535, 0.32221825099986745, 0.35182066400011536, 0.35663595400001213, 0.3842096920000131, 0.4138117239999701]
# 64
# [0.04606491999993523, 0.06779569900027127, 0.09685762100025386, 0.12219671000002563, 0.14586037300023236, 0.1700412850000248, 0.21632630700014488, 0.23113141200019527, 0.2638085839998894, 0.2760139719998733, 0.3001248149998901, 0.30320839800015165, 0.32136949599998843, 0.3438082170000598]

ml_labels = ['DVC','RLVC','LSVC']
com_t = [[0.031189141000140808, 0.061611389999825406, 0.08575277299974005, 0.11296145900018928, 0.14397867699995004, 0.1720223359998272, 0.20626382000023114, 0.23150906300020324, 0.262774699999909, 0.29222327299953577, 0.32226526900012686, 0.3528986520000217, 0.38183643099978326, 0.41159681199997067],
[0.03548506700008147, 0.07703001000004406, 0.11634391000029609, 0.1602356679998138, 0.20212238199974308, 0.24543897899980038, 0.28723739499992007, 0.33600276399988616, 0.3826641949999612, 0.42505351599993446, 0.4697764459995142, 0.5151504109999223, 0.5607268250005291, 0.6026666810003007],
[0.0538, 0.0816, 0.107, 0.136, 0.167, 0.194, 0.245, 0.266, 0.311, 0.322, 0.352, 0.354, 0.387, 0.413]
]
image_nums = [range(1,15) for _ in range(2)]
line_plot(image_nums,com_t,ml_labels,
		'/home/bo/Dropbox/Research/SIGCOMM22/images/scalability.eps',
		'Number of images','Time (s)',xticks=[0,5,10,15])

def bar_plot(avg,std,path,color,ylabel,yticks=None):
	N = len(avg)
	ind = np.arange(N)  # the x locations for the groups
	width = 0.5       # the width of the bars
	fig, ax = plt.subplots()
	ax.grid(zorder=0)
	ax.set_axisbelow(True)
	ax.bar(ind, avg, width, color=color, \
		yerr=std, error_kw=dict(lw=1, capsize=1, capthick=1))
	ax.set_ylabel(ylabel, fontsize = labelsize)
	ax.set_xticks(ind)
	ax.set_xticklabels(labels[:N])
	if yticks is not None:
		plt.yticks( yticks )
	xleft, xright = ax.get_xlim()
	ybottom, ytop = ax.get_ylim()
	ratio = 0.3
	ax.set_aspect(abs((xright-xleft)/(ybottom-ytop))*ratio)
	plt.tight_layout()
	fig.savefig(path,bbox_inches='tight')

com_speeds_avg = [56.96,57.35,27.90,19.31,32.89] # 27.07,32.89,36.83
com_speeds_std = [1.96,1.35,1.90,1.31,1.84]
bar_plot(com_speeds_avg,com_speeds_std,
		'/home/bo/Dropbox/Research/SIGCOMM22/images/speed.eps',
		colors[1],'Speed (fps)',yticks=np.arange(0,70,15))

rbr_avg = [0.28,0.29,0.46,0.58,0.37]
rbr_std = [0.08,0.09,0.06,0.08,0.07]
bar_plot(rbr_avg,rbr_std,
		'/home/bo/Dropbox/Research/SIGCOMM22/images/rebuffer.eps',
		colors[4],'Rebuffer Rate',yticks=np.arange(0,1,0.2))

latency_avg = [0.575,0.593,0.576,0.706,0.963]
latency_std = [0.075,0.093,0.01,0.076,0.063]
bar_plot(latency_avg,latency_std,
		'/home/bo/Dropbox/Research/SIGCOMM22/images/latency.eps',
		colors[3],'Start-up Latency',yticks=np.arange(0,1,0.2))

fps_arr = [[] for _ in range(5)]
rbf_arr = [[] for _ in range(5)]
with open('server.log','r') as f:
	count = 0
	for line in f.readlines():
		line = line.strip()
		line = line.split(' ')
		fps = float(line[3])
		rbf = float(line[4])
		pos = count%5
		if pos==2:
			pos=3
		elif pos==3:
			pos=2
		fps_arr[pos] += [fps]
		rbf_arr[pos] += [rbf]
		count += 1
	# switch 2,3
fps_arr = np.array(fps_arr)
rbf_arr = np.array(rbf_arr)

fps_avg = np.mean(fps_arr,1)
fps_std = np.std(fps_arr,1)
rbf_avg = np.mean(rbf_arr,1)
rbf_std = np.std(rbf_arr,1)
bar_plot(fps_avg,fps_std,
		'/home/bo/Dropbox/Research/SIGCOMM22/images/speed2.jpg',
		colors[1],'Speed (fps)',yticks=np.arange(0,45,15))
bar_plot(rbf_avg,rbf_std,
		'/home/bo/Dropbox/Research/SIGCOMM22/images/rebuffer2.jpg',
		colors[3],'Rebuffer Rate',yticks=np.arange(0,0.3,0.1))