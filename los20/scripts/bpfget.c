/* 直接测 BPF_OBJ_GET 的两种形式，定位 netd 的 EPERM 来源
 * 编译: 用设备自带 clang 交叉编译（host 侧用 aarch64 gcc/clang）
 *   aarch64-linux-gnu-gcc -static -o bpfget bpfget.c
 * 运行（设备 root）:
 *   ./bpfget /sys/fs/bpf/netd_shared/prog_netd_cgroupskb_egress_stats
 */
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <sys/syscall.h>

#define BPF_OBJ_GET 7
#define BPF_OBJ_GET_INFO_BY_FD 15

union bpf_attr_obj {
    struct {
        uint64_t pathname;
        uint32_t bpf_fd;
        uint32_t file_flags;
    };
};

struct bpf_prog_info_min {
    uint32_t type;
    uint32_t id;
    uint8_t tag[8];
    uint32_t jited_prog_len;
    uint32_t xlated_prog_len;
    uint64_t jited_prog_insns;
    uint64_t xlated_prog_insns;
} __attribute__((aligned(8)));

union bpf_attr_info {
    struct {
        uint32_t bpf_fd;
        uint32_t info_len;
        uint64_t info;
    } info;
};

static long sys_bpf(int cmd, void *attr, unsigned int size)
{
    return syscall(__NR_bpf, cmd, attr, size);
}

int main(int argc, char **argv)
{
    if (argc < 2) { fprintf(stderr, "用法: %s <pin路径>\n", argv[0]); return 2; }
    const char *p = argv[1];

    /* ① pathname 形式：pathname=路径, bpf_fd=0, file_flags=0 */
    union bpf_attr_obj a;
    memset(&a, 0, sizeof(a));
    a.pathname = (uint64_t)(uintptr_t)p;
    errno = 0;
    long fd1 = sys_bpf(BPF_OBJ_GET, &a, sizeof(a));
    printf("① path 形式  BPF_OBJ_GET(pathname=%s) -> %ld (errno=%d %s)\n",
           p, fd1, errno, strerror(errno));

    /* ② 直接用 open() 打开 pinned 文件 */
    int fd2 = open(p, O_RDWR);
    printf("② open(O_RDWR)                       -> %d (errno=%d %s)\n",
           fd2, errno, strerror(errno));
    if (fd2 < 0) { fd2 = open(p, O_RDONLY); printf("   open(O_RDONLY) -> %d (%s)\n", fd2, strerror(errno)); }

    /* ③ fd 形式：bpf_fd=<已打开的 fd>，看内核是否接受 */
    if (fd2 >= 0) {
        union bpf_attr_obj b;
        memset(&b, 0, sizeof(b));
        b.bpf_fd = (uint32_t)fd2;
        errno = 0;
        long fd3 = sys_bpf(BPF_OBJ_GET, &b, sizeof(b));
        printf("③ fd   形式  BPF_OBJ_GET(bpf_fd=%d)   -> %ld (errno=%d %s)\n",
               fd2, fd3, errno, strerror(errno));

        /* ④ BPF_OBJ_GET_INFO_BY_FD —— 这才是 netd 真正需要的 */
        struct bpf_prog_info_min info;
        memset(&info, 0, sizeof(info));
        union bpf_attr_info c;
        memset(&c, 0, sizeof(c));
        c.info.bpf_fd = (uint32_t)fd2;
        c.info.info_len = sizeof(info);
        c.info.info = (uint64_t)(uintptr_t)&info;
        errno = 0;
        long r = sys_bpf(BPF_OBJ_GET_INFO_BY_FD, &c, sizeof(c));
        printf("④ BPF_OBJ_GET_INFO_BY_FD(fd=%d)      -> %ld (errno=%d %s)\n",
               fd2, r, errno, strerror(errno));
        if (r == 0)
            printf("   info: type=%u id=%d xlated_len=%u\n",
                   info.type, (int)info.id, info.xlated_prog_len);
    }
    return 0;
}
