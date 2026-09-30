
typedef unsigned long u64; typedef unsigned int u32; typedef unsigned char u8;
static long S4(long n,long a,long b,long c,long d){register long x0 __asm__("x0")=a,x1 __asm__("x1")=b,x2 __asm__("x2")=c,x3 __asm__("x3")=d,x8 __asm__("x8")=n;
 __asm__ volatile("svc #0":"+r"(x0):"r"(x1),"r"(x2),"r"(x3),"r"(x8):"memory"); return x0;}
static void P(const char*s){long n=0;while(s[n])n++;S4(64,1,(long)s,n,0);}
static void L(long v){char b[24];int i=23;b[i]=0;int g=v<0;unsigned long u=g?-(unsigned long)v:(unsigned long)v;
 if(!u)b[--i]='0';while(u){b[--i]='0'+(u%10);u/=10;}if(g)b[--i]='-';P(&b[i]);}
static u8 BUF[64] __attribute__((aligned(8)));
static long get_map(const char*p, u32 fl){for(int i=0;i<64;i++)BUF[i]=0;*(u64*)BUF=(u64)p;*(u32*)(BUF+12)=fl;return S4(280,7,(long)BUF,48,0);}
void _start(void){
  P("map_netd_iface_stats_map  flags=0(RW)   : "); L(get_map("/sys/fs/bpf/netd_shared/map_netd_iface_stats_map",0)); P("\n");
  P("map_netd_iface_stats_map  BPF_F_RDONLY  : "); L(get_map("/sys/fs/bpf/netd_shared/map_netd_iface_stats_map",8)); P("\n");
  P("map_netd_configuration_map flags=0      : "); L(get_map("/sys/fs/bpf/netd_shared/map_netd_configuration_map",0)); P("\n");
  P("map_netd_uid_owner_map     flags=0      : "); L(get_map("/sys/fs/bpf/netd_shared/map_netd_uid_owner_map",0)); P("\n");
  S4(93,0,0,0,0); __builtin_unreachable();
}
