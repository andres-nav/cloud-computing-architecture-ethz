import time
import sys

def read_proc_stat():
    with open("/proc/stat") as f:
        return [(cols[3], sum(cols))
           for line in f
           if line.startswith("cpu") and line[3].isdigit()
           for cols in [list(map(int, line.split()[1:9]))]
        ]

if __name__ == "__main__":
    import datetime
    out_file = sys.argv[1]
    with open(out_file, "w") as f:
        f.write("timestamp,cpu0,cpu1,cpu2,cpu3\n")
        while True:
            before = read_proc_stat()
            time.sleep(1.0)
            after = read_proc_stat()
            diffs = ((idle_a - idle_b, tot_a - tot_b) for ((idle_b, tot_b), (idle_a, tot_a)) in zip(before, after))
            cpu_util = [(0.0 if total == 0 else 1.0 - idle / total) for (idle, total) in diffs]
            row = datetime.datetime.now().isoformat() + "," + ",".join(f"{u*100:.1f}" for u in cpu_util)
            f.write(row + "\n")
            f.flush()
