/* 极简崩溃抓取器：ptrace 附加到目标进程，等它被 SIGABRT/SIGSEGV 打死时
 * 打印崩溃线程的调用栈（用帧指针回溯）、关键寄存器、以及末尾的可读字符串。
 *
 * 背景：本机 3.10 内核上 debuggerd/crash_dump 不可用
 *   （crash_dump failed to dump process: failed to waitpid on child: No child processes）
 *   /data/tombstones 也始终为空 → 拿不到 native 栈。
 *
 * 编译（host，使用 AOSP 内核 clang + lld）：
 *   clang --target=aarch64-linux-android21 -O1 -nostdlib -fuse-ld=ld.lld -Wl,-e,_start
 * 用法（设备 root）：
 *   crashgrab <pid>
 */
typedef unsigned long u64;
typedef unsigned int u32;
typedef unsigned char u8;

/* ---- arm64 通用系统调用号 ---- */
#define NR_gettid     178
#define NR_read       63
#define NR_wait4      260
#define NR_lseek      62
#define NR_ptrace_std 117
#define NR_write      64
#define NR_openat     56
#define NR_close      57
#define NR_ptrace     117
#define NR_exit       93
#define NR_exit_group 94
#define NR_nanosleep  101
#define NR_getpid     172

/* ptrace 请求 */
#define PTRACE_ATTACH     16
#define PTRACE_CONT       7
#define PTRACE_GETREGSET  0x4204
#define PTRACE_SETOPTIONS 0x4200
#define PTRACE_SEIZE      0x4206
#define PTRACE_INTERRUPT  0x4207
#define NT_PRSTATUS 1
#define NT_PRFPREG  2

/* 错误码/信号 */
#define SIGTRAP 5
#define SIGABRT 6
#define SIGSEGV 11

static long S4(long n, long a, long b, long c, long d) {
    register long x0 __asm__("x0") = a, x1 __asm__("x1") = b, x2 __asm__("x2") = c,
                  x3 __asm__("x3") = d, x8 __asm__("x8") = n;
    __asm__ volatile("svc #0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x3), "r"(x8) : "memory");
    return x0;
}
static long S5(long n, long a, long b, long c, long d, long e) {
    register long x0 __asm__("x0") = a, x1 __asm__("x1") = b, x2 __asm__("x2") = c,
                  x3 __asm__("x3") = d, x4 __asm__("x4") = e, x8 __asm__("x8") = n;
    __asm__ volatile("svc #0" : "+r"(x0) : "r"(x1), "r"(x2), "r"(x3), "r"(x4), "r"(x8) : "memory");
    return x0;
}
static void P(const char *s) { long n = 0; while (s[n]) n++; S4(NR_write, 1, (long)s, n, 0); }
static void LN(long v) {
    char b[24]; int i = 23; b[i] = 0; int neg = v < 0;
    unsigned long u = neg ? -(unsigned long)v : (unsigned long)v;
    if (!u) b[--i] = '0';
    while (u) { b[--i] = '0' + (u % 10); u /= 10; }
    if (neg) b[--i] = '-';
    P(&b[i]);
}
static void HX(u64 v) {
    char b[20]; int i = 18; b[19] = 0;
    b[18] = 0;
    if (!v) { P("0x0"); return; }
    while (v && i > 0) { int d = (int)(v & 0xf); b[i--] = d < 10 ? '0' + d : 'a' + d - 10; v >>= 4; }
    P("0x"); P(&b[i + 1]);
}

static u8 RBUF[1024];
static u8 WBUF[256];

static long dev_open(const char *path, long flags) {
    return S4(NR_openat, -100, (long)path, flags, 0);
}

static void write_file(const char *path, const char *data, long len) {
    long fd = dev_open(path, 0x441 /*O_WRONLY|O_CREAT|O_APPEND*/);
    if (fd < 0) return;
    S4(NR_write, fd, (long)data, len, 0);
    S4(NR_close, fd, 0, 0, 0);
}

/* 用 ptrace 读目标进程内存 */
static long read_mem(long pid, u64 addr, void *buf, long len) {
    /* 用 /proc/pid/mem */
    static char path[64];
    /* 构造 "/proc/<pid>/mem" */
    const char *pre = "/proc/";
    int k = 0;
    while (*pre) path[k++] = *pre++;
    char tmp[16]; int t = 0;
    if (pid == 0) tmp[t++] = '0';
    while (pid) { tmp[t++] = '0' + (pid % 10); pid /= 10; }
    while (t) path[k++] = tmp[--t];
    const char *post = "/mem";
    while (*post) path[k++] = *post++;
    path[k] = 0;

    long fd = dev_open(path, 0 /*O_RDONLY*/);
    if (fd < 0) return -1;
    /* lseek(fd, addr, SEEK_SET=0) : arm64 lseek = 62 */
    long off = S5(NR_lseek, fd, (long)addr, 0, 0, 0);
    long n = -1;
    if (off >= 0) n = S4(NR_read, fd, (long)buf, len, 0);
    S4(NR_close, fd, 0, 0, 0);
    return n;
}

void _start(void) {
    /* 取 argv[1] = pid（本程序用 -nostdlib，需自己从栈上取） */
    long *sp; __asm__ volatile("mov %0, sp" : "=r"(sp));
    long argc = sp[0];
    char **argv = (char **)&sp[1];
    if (argc < 2) { P("用法: crashgrab <pid>\n"); S4(NR_exit_group, 2, 0, 0, 0); }

    long pid = 0;
    for (char *p = argv[1]; *p; p++) { if (*p < '0' || *p > '9') break; pid = pid * 10 + (*p - '0'); }
    P("[crashgrab] 目标 pid="); LN(pid); P("\n");

    long r = S4(NR_ptrace, PTRACE_SEIZE, pid, 0, 0);
    P("[crashgrab] PTRACE_SEIZE -> "); LN(r); P("\n");
    if (r < 0) {
        /* 退回 ATTACH */
        r = S4(NR_ptrace, PTRACE_ATTACH, pid, 0, 0);
        P("[crashgrab] PTRACE_ATTACH -> "); LN(r); P("\n");
    }
    if (r < 0) { P("attach/seize 失败（需要 root + CAP_SYS_PTRACE）\n"); S4(NR_exit_group, 1, 0, 0, 0); }

    /* wait4(pid, &status, 0, 0) 阻塞等状态变化 —— 崩溃时就能拿到 */
    static long status;
    long w;
    int reported = 0;
    for (int loop = 0; loop < 200; loop++) {
        w = S4(NR_wait4, pid, (long)&status, 0, 0);
        if (w < 0) { P("[crashgrab] wait4 出错，目标可能已退出\n"); break; }
        int sig = (int)(status & 0x7f);
        int stopped = (int)((status >> 8) & 0xff);
        if (sig == 0x7f) {
            /* 被信号暂停 */
            if (stopped == SIGABRT || stopped == SIGSEGV) {
                P("\n[crashgrab] 捕获信号 "); LN(stopped); P("，开始回溯\n");
                /* 读寄存器：用 PTRACE_GETREGSET(pid, NT_PRSTATUS, iov) */
                struct { u64 base; u64 len; } iov;
                static u8 regs[512] __attribute__((aligned(16)));
                iov.base = (u64)regs; iov.len = sizeof(regs);
                long g = S4(NR_ptrace, PTRACE_GETREGSET, pid, NT_PRSTATUS, (long)&iov);
                P("[crashgrab] GETREGSET -> "); LN(g); P(" len="); LN((long)iov.len); P("\n");
                if (g == 0) {
                    u64 *R = (u64 *)regs;
                    /* struct user_pt_regs: x0..x30, sp, pc, pstate */
                    P("  pc="); HX(R[32]); P("  lr="); HX(R[30]); P("  sp="); HX(R[31]); P("\n");
                    /* 用 x29(帧指针, R[29]) 与 lr 做朴素回溯 */
                    u64 fp = R[29];
                    P("  -- 帧回溯（fp 链）--\n");
                    for (int i = 0; i < 24 && fp > 0x1000; i++) {
                        u64 frame[2];
                        if (read_mem(pid, fp, frame, 16) != 16) { P("   (读内存失败，停止)\n"); break; }
                        P("   #"); LN(i); P(" ret="); HX(frame[1]); P(" (fp="); HX(fp); P(")\n");
                        if (frame[0] <= fp) break;
                        fp = frame[0];
                    }
                }
                /* 尝试读崩溃线程名 */
                reported = 1;
                break;
            }
            /* 其它停止（SIGTRAP 等）→ 放行 */
            S4(NR_ptrace, PTRACE_CONT, pid, 0, stopped);
        } else if (sig != 0) {
            P("[crashgrab] 目标被信号终结: "); LN(sig); P("\n");
            break;
        } else {
            P("[crashgrab] 目标已退出，status="); LN((long)status); P("\n");
            break;
        }
    }
    if (!reported) P("[crashgrab] 未捕获到目标信号（目标可能已重启）\n");
    P("[crashgrab] 结束\n");
    S4(NR_exit_group, 0, 0, 0, 0);
    __builtin_unreachable();
}
