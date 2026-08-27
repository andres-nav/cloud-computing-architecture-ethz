from matplotlib.colors import ListedColormap
from typing import cast
import matplotlib
import numpy as np
import matplotlib.pyplot as plt
import re
import os
import glob

def parse_time(time_str):
    """Convert '1m31.468s' or '0m24.316s' format to seconds."""
    m = re.match(r'(\d+)m([\d.]+)s', time_str)
    if m:
        return int(m.group(1)) * 60 + float(m.group(2))
    return None

def get_stats(bench, threads):
    base_dir = 'part2/results/part2b'
    pattern = os.path.join(base_dir, f'{bench}_{threads}t', '*.log')
    files = glob.glob(pattern)
    times = []
    
    for file in files:
        with open(file, 'r') as f:
            content = f.read()
            match = re.search(r'^real\t(\d+m[\d.]+s)', content, re.MULTILINE)
            if match:
                times.append(parse_time(match.group(1)))
    
    if times:
        return np.mean(times), np.std(times)
    return 0, 0

streamcluster_stats = get_stats('streamcluster', 4)
vips_stats = get_stats('vips', 4)
radix_stats = get_stats('radix', 4)

canneal_stats = get_stats('canneal', 4)
freqmine_stats = get_stats('freqmine', 4)
barnes_stats = get_stats('barnes', 4)

fig, ax = plt.subplots(figsize=(12, 5))

queues = ['Queue 1 (Cores 0-3)', 'Queue 2 (Cores 4-7)']

queue_data = [
    [('streamcluster', *streamcluster_stats), ('vips', *vips_stats), ('radix', *radix_stats)],
    [('canneal', *canneal_stats), ('freqmine', *freqmine_stats), ('barnes', *barnes_stats)]
]

colors = matplotlib.colormaps['tab10']
color_idx = 0

for i, q_data in enumerate(queue_data):
    left = 0
    total_variance = 0
    for job, mean_time, std_time in q_data:
        ax.barh(queues[i], mean_time, left=left, height=0.5, 
                color=colors(color_idx % colors.N), edgecolor='black')
        
        ax.text(left + mean_time / 2, i, f'{job}\n({int(round(mean_time))}s)', 
                ha='center', va='center', color='white', 
                fontweight='bold', fontsize=10)
        
        ax.errorbar(left + mean_time / 2, i, xerr=std_time, color='black', 
                    capsize=4, elinewidth=1.5, fmt='none', alpha=0.8, zorder=3)
        
        left += mean_time
        total_variance += std_time ** 2
        color_idx += 1
    
    accumulated_std = np.sqrt(total_variance)
    
    ax.errorbar(left, i, xerr=accumulated_std, color='red', 
                capsize=8, elinewidth=2.5, fmt='none', 
                label='Total Std Dev' if i == 0 else "", zorder=4)
    
    ax.text(left + accumulated_std + 4, i, f'Total:\n{int(round(left))}s ± {int(round(accumulated_std))}s', 
            va='center', fontsize=10, fontweight='bold', color='black')

ax.set_xlabel('Total Makespan Time (sec)', fontsize=12, fontweight='bold')
ax.set_title('4/4 Thread Scheduling Strategy', fontsize=14, fontweight='bold')

max_makespan = max(sum(time for _, time, _ in q) + np.sqrt(sum(std**2 for _, _, std in q)) for q in queue_data)
ax.set_xlim(0, max_makespan + 45)

handles, labels = ax.get_legend_handles_labels()
if handles:
    ax.legend(loc='lower right')

plt.tight_layout()
plt.savefig('oliver_44_strategy_plot.png', dpi=300)

print("saved to oliver_44_strategy_plot.png")
for i, q in enumerate(queue_data):
    total_mean = sum(time for _, time, _ in q)
    total_std = np.sqrt(sum(std**2 for _, _, std in q))
    print(f"Queue {i+1} Total Makespan: {total_mean:.1f}s ± {total_std:.1f}s")
