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

# from matplotlib import rc,rcParams
# # activate latex text rendering
# rc('text', usetex=True)
# rc('axes', linewidth=2)
# rc('font', weight='bold')
# rcParams['text.latex.preamble'] = [r'\usepackage{sfmath} \boldmath']


colors = ['#08A720','#86A8E7','#9D5FFB','#E09C1A','#D00C0E']

bpps = [[0.14,0.21,0.33,0.5],
		[0.16,0.25,0.39,0.59],
		[0.187],
		[0.154],
		[0.123,0.181,0.284,0.3925]]
PSNRs = [[28.37,29.96,31.31,32.38],
		[29.56,30.90,31.96,32.82],
		[30.82],
		[29.45],
		[28.98,30.54,31.54,32.24]]
labels = ['H.264','H.265','RLVC','DVC','LSVC']
markers = ['p','s','o','>','v']

fig, ax = plt.subplots()
ax.grid(zorder=0)
for i in range(len(bpps)):
	bpp,PSNR = bpps[i],PSNRs[i]
	plt.plot(bpp, PSNR, color = colors[i], marker = markers[i], label = labels[i], linewidth=2)
plt.xlabel('bpp', fontsize = labelsize)
plt.ylabel('PSNR (dB)', fontsize = labelsize)
# plt.xticks( np.arange(4) )
plt.tight_layout()
plt.legend(loc='best',fontsize = lfsize)
# ax.legend(loc='upper center', bbox_to_anchor=(0.5, 1.25), fontsize = 13,
#           fancybox=False, shadow=False, ncol=3)
# plt.legend(bbox_to_anchor=(1.05, 1), loc=2, borderaxespad=0.,fontsize = lfsize)
# plt.xlim((0.8,3.2))
# plt.ylim((-40,90))

plt.tight_layout()
fig.savefig('images/rate-distortion.eps',bbox_inches='tight')

com_speeds_avg = [56.96,57.35,19.31,27.90,26.84]
com_speeds_std = [1.96,1.35,1.31,1.90,1.84]
N = len(com_speeds_avg)

ind = np.arange(N)  # the x locations for the groups
width = 0.5       # the width of the bars
fig, ax = plt.subplots()
ax.grid(zorder=0)
ax.set_axisbelow(True)
ax.bar(ind, com_speeds_avg, width, color=colors[1], \
	yerr=com_speeds_std, error_kw=dict(lw=1, capsize=1, capthick=1))

ax.set_ylabel('Speed (fps)', fontsize = labelsize)
ax.set_xticks(ind)
ax.set_xticklabels(labels)
plt.yticks( np.arange(0,70,20) )

xleft, xright = ax.get_xlim()
ybottom, ytop = ax.get_ylim()
ratio = 0.3
ax.set_aspect(abs((xright-xleft)/(ybottom-ytop))*ratio)

plt.tight_layout()
fig.savefig('images/speed.eps',bbox_inches='tight')
