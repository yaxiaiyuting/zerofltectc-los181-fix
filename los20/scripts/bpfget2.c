
#define __NR_bpf 280
long syscall(long, ...);
int printf(const char *, ...);
void *memset(void *, int, unsigned long);

union obj { struct { unsigned long long pathname; unsigned int bpf_fd; unsigned int file_flags; } o; };
union inf { struct { unsigned int bpf_fd; unsigned int info_len; unsigned long long info; } i; };
struct pinfo { unsigned int type, id; unsigned char tag[8]; unsigned int jl, xl; unsigned long long ji, xi; } __attribute__((aligned(8)));

int main(int argc, char **argv) {
    if (argc < 2) return 2;
    union obj a; memset(&a, 0, sizeof(a));
    a.o.pathname = (unsigned long long)(unsigned long)argv[1];
    long r1 = syscall(__NR_bpf, 7, &a, sizeof(a));
    printf("1) BPF_OBJ_GET(path)      = %ld\n", r1);

    int fd = syscall(56 /*openat*/, -100, argv[1], 0 /*O_RDONLY*/, 0);
    printf("2) openat(path, O_RDONLY) = %d\n", fd);
    if (fd >= 0) {
        union obj b; memset(&b, 0, sizeof(b));
        b.o.bpf_fd = (unsigned int)fd;
        long r2 = syscall(__NR_bpf, 7, &b, sizeof(b));
        printf("3) BPF_OBJ_GET(bpf_fd)    = %ld\n", r2);

        struct pinfo pi; memset(&pi, 0, sizeof(pi));
        union inf c; memset(&c, 0, sizeof(c));
        c.i.bpf_fd = (unsigned int)fd;
        c.i.info_len = sizeof(pi);
        c.i.info = (unsigned long long)(unsigned long)&pi;
        long r3 = syscall(__NR_bpf, 15, &c, sizeof(c));
        printf("4) OBJ_GET_INFO_BY_FD     = %ld  type=%u id=%d xl=%u\n", r3, pi.type, (int)pi.id, pi.xl);
    }
    return 0;
}
