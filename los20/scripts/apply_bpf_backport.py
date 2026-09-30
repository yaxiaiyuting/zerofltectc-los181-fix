#!/usr/bin/env python3
"""把 eBPF 回移打进 SM-G9209 的 LOS 20 内核（3.10.108, lineage-20 分支）

为什么需要这个补丁
------------------
Android 13 的 bpfloader 通过 BPF_OBJ_GET_INFO_BY_FD 给已加载的程序/Map 查 id，
用它做「同一个程序不重复加载」的去重。ROM 内核（内核仓库 lineage-20 分支）
**没有实现这个命令** —— syscall 的 switch 落到 default 返回 -EINVAL，
于是去重失效、程序被反复加载、locked_vm 顶爆 memlock、bpfloader 退出非 0；
而 `bpfloader.rc` 写死了 `reboot_on_failure reboot,bpfloader-failed` → 无限重启。

补丁内容严格取自内核仓库 `lineage-21.0-bpf-alpha` 分支（3.10.108 上的 eBPF 回移），
逐块最小化移植：
  1. include/linux/kernel.h            + u64_to_user_ptr()
  2. include/uapi/linux/bpf.h          + BPF_OBJ_GET_INFO_BY_FD / info 字段 /
                                         bpf_prog_info / bpf_map_info
  3. init/Kconfig                      + CONFIG_BPF_UNPRIV_DEFAULT_OFF
  4. kernel/bpf/syscall.c              + check_uarg_tail_zero / *_get_info_by_fd /
                                         BPF_OBJ_GET_INFO_BY_FD case，
                                         并把 syscall 里原来的 tail-zero 内联逻辑换成调用
  5. arch/arm64/configs/*_defconfig    + CONFIG_BPF_UNPRIV_DEFAULT_OFF=y

用法:
  apply_bpf_backport.py <内核源码根目录> [--defconfig 名字]
"""
import os
import re
import sys

# ---------------------------------------------------------------- 代码片段
U64_TO_USER_PTR = '''
#define u64_to_user_ptr(x) (		\\
{					\\
	typeof(x) x_ = (x);		\\
	(void __user *)(uintptr_t)x_;	\\
}					\\
)
'''

UAPI_ENUM = '\tBPF_OBJ_GET_INFO_BY_FD = BPF_PROG_DETACH + 6,\n'

UAPI_INFO_FIELD = '''	struct { /* anonymous struct used by BPF_OBJ_GET_INFO_BY_FD */
		__u32		bpf_fd;
		__u32		info_len;
		__aligned_u64	info;
	} info;
'''

UAPI_INFO_STRUCTS = '''
#define BPF_TAG_SIZE	8

struct bpf_prog_info {
	__u32 type;
	__u32 id;
	__u8  tag[BPF_TAG_SIZE];
	__u32 jited_prog_len;
	__u32 xlated_prog_len;
	__aligned_u64 jited_prog_insns;
	__aligned_u64 xlated_prog_insns;
} __attribute__((aligned(8)));

struct bpf_map_info {
	__u32 type;
	__u32 id;
	__u32 key_size;
	__u32 value_size;
	__u32 max_entries;
	__u32 map_flags;
} __attribute__((aligned(8)));
'''

KCONFIG_ENTRY = '''
config BPF_UNPRIV_DEFAULT_OFF
	bool "Disable unprivileged BPF by default"
	depends on BPF_SYSCALL
	help
	  Disables unprivileged BPF by default by setting the corresponding
	  /proc/sys/kernel/unprivileged_bpf_disabled knob to 2. An admin can
	  still reenable it by setting it to 0 later on, or permanently
	  disable it by setting it to 1 (which is what Android wants).
'''

SYSCALL_FUNCS = '''
static int check_uarg_tail_zero(void __user *uaddr,
				size_t expected_size,
				size_t actual_size)
{
	unsigned char __user *addr;
	unsigned char __user *end;
	unsigned char val;
	int err;

	if (actual_size <= expected_size)
		return 0;

	addr = uaddr + expected_size;
	end  = uaddr + actual_size;

	for (; addr < end; addr++) {
		err = get_user(val, addr);
		if (err)
			return err;
		if (val)
			return -E2BIG;
	}

	return 0;
}

static int bpf_prog_get_info_by_fd(struct bpf_prog *prog,
				   const union bpf_attr *attr,
				   union bpf_attr __user *uattr)
{
	struct bpf_prog_info __user *uinfo = u64_to_user_ptr(attr->info.info);
	struct bpf_prog_info info = {};
	u32 info_len = attr->info.info_len;
	char __user *uinsns;
	u32 ulen;
	int err;

	err = check_uarg_tail_zero(uinfo, sizeof(info), info_len);
	if (err)
		return err;
	info_len = min_t(u32, sizeof(info), info_len);

	if (copy_from_user(&info, uinfo, info_len))
		return err;

	info.type = prog->type;
	info.id = -1; // prog->aux->id;

	// memcpy(info.tag, prog->tag, sizeof(prog->tag));

	if (!capable(CAP_SYS_ADMIN)) {
		info.jited_prog_len = 0;
		info.xlated_prog_len = 0;
		goto done;
	}

	ulen = info.xlated_prog_len;
	info.xlated_prog_len = bpf_prog_size(prog->len);
	if (info.xlated_prog_len && ulen) {
		uinsns = u64_to_user_ptr(info.xlated_prog_insns);
		ulen = min_t(u32, info.xlated_prog_len, ulen);
		if (copy_to_user(uinsns, prog->insnsi, ulen))
			return -EFAULT;
	}

done:
	if (copy_to_user(uinfo, &info, info_len) ||
	    put_user(info_len, &uattr->info.info_len))
		return -EFAULT;

	return 0;
}

static int bpf_map_get_info_by_fd(struct bpf_map *map,
				  const union bpf_attr *attr,
				  union bpf_attr __user *uattr)
{
	struct bpf_map_info __user *uinfo = u64_to_user_ptr(attr->info.info);
	struct bpf_map_info info = {};
	u32 info_len = attr->info.info_len;
	int err;

	err = check_uarg_tail_zero(uinfo, sizeof(info), info_len);
	if (err)
		return err;
	info_len = min_t(u32, sizeof(info), info_len);

	info.type = map->map_type;
	info.key_size = map->key_size;
	info.value_size = map->value_size;
	info.max_entries = map->max_entries;
	info.map_flags = map->map_flags;

	if (copy_to_user(uinfo, &info, info_len) ||
	    put_user(info_len, &uattr->info.info_len))
		return -EFAULT;

	return 0;
}

#define BPF_OBJ_GET_INFO_BY_FD_LAST_FIELD info.info

static int bpf_obj_get_info_by_fd(const union bpf_attr *attr,
				  union bpf_attr __user *uattr)
{
	int ufd = attr->info.bpf_fd;
	struct fd f;
	int err;

	if (CHECK_ATTR(BPF_OBJ_GET_INFO_BY_FD))
		return -EINVAL;

	f = fdget(ufd);
	if (!f.file)
		return -EBADFD;

	if (f.file->f_op == &bpf_prog_fops)
		err = bpf_prog_get_info_by_fd(f.file->private_data, attr,
					      uattr);
	else if (f.file->f_op == &bpf_map_fops)
		err = bpf_map_get_info_by_fd(f.file->private_data, attr,
					     uattr);
	else
		err = -EINVAL;

	fdput(f);
	return err;
}

'''

SYSCALL_CASE = '''	case BPF_OBJ_GET_INFO_BY_FD:
		err = bpf_obj_get_info_by_fd(&attr, uattr);
		break;
'''


def patch_file(path, fn, label, expect=1):
    s = open(path, encoding='utf-8', errors='surrogateescape').read()
    new, n = fn(s)
    if n == 0 and expect > 0:
        print(f'   ⚠️ {label}: 未找到锚点（可能已打过补丁？）')
        return False
    open(path, 'w', encoding='utf-8', errors='surrogateescape').write(new)
    print(f'   ✅ {label}')
    return True


def main():
    root = sys.argv[1]
    defconfigs = []
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == '--defconfig':
            defconfigs.append(sys.argv[i + 1]); i += 2
        else:
            i += 1
    if not defconfigs:
        defconfigs = ['arch/arm64/configs/exynos7420-zeroflte_defconfig']

    print(f'内核根目录: {root}')

    # ---- 1) include/linux/kernel.h: u64_to_user_ptr ----
    p = os.path.join(root, 'include/linux/kernel.h')
    def f1(s):
        if 'define u64_to_user_ptr' in s:
            return s, 0
        m = re.search(r'^#define\s+ALIGN\(x,\s*a\)', s, re.M)
        if not m:
            m = re.search(r'^#define\s+PTR_ALIGN\(', s, re.M)
        assert m, 'kernel.h 找不到 ALIGN 锚点'
        # 插到 ALIGN 定义之后的空行处
        end = s.index('\n', m.end())
        return s[:end + 1] + U64_TO_USER_PTR + s[end + 1:], 1
    patch_file(p, f1, 'include/linux/kernel.h += u64_to_user_ptr()')

    # ---- 2) include/uapi/linux/bpf.h ----
    p = os.path.join(root, 'include/uapi/linux/bpf.h')
    def f2(s):
        n = 0
        if 'BPF_OBJ_GET_INFO_BY_FD' not in s:
            s = s.replace('\tBPF_PROG_DETACH,\n', '\tBPF_PROG_DETACH,\n' + UAPI_ENUM, 1)
            n += 1
        if 'used by BPF_OBJ_GET_INFO_BY_FD' not in s:
            # 必须锚定到 union bpf_attr 内部的结尾：
            # 文件里还有别的 __aligned(8) 结尾（bpf_prog_info 等），
            # 直接 re.search 会匹配到 union bpf_attr 自己的收尾括号后面，导致
            # info 字段被插到 union 外面 → "no member named 'info' in union bpf_attr"
            um = re.search(r'^union bpf_attr \{\n', s, re.M)
            assert um, 'bpf.h 找不到 union bpf_attr'
            tail = re.search(r'^\} __attribute__\(\(aligned\(8\)\)\);\n', s[um.end():], re.M)
            assert tail, 'bpf.h 找不到 union bpf_attr 的收尾'
            at = um.end() + tail.start()
            s = s[:at] + UAPI_INFO_FIELD + s[at:]
            n += 1
        if 'struct bpf_prog_info' not in s:
            m = re.search(r'^#endif /\* _UAPI__LINUX_BPF_H__ \*/', s, re.M)
            assert m, 'bpf.h 找不到结尾 #endif'
            s = s[:m.start()] + UAPI_INFO_STRUCTS + '\n' + s[m.start():]
            n += 1
        return s, n
    patch_file(p, f2, 'include/uapi/linux/bpf.h += BPF_OBJ_GET_INFO_BY_FD 与 info 结构')

    # ---- 3) init/Kconfig ----
    p = os.path.join(root, 'init/Kconfig')
    def f3(s):
        if 'BPF_UNPRIV_DEFAULT_OFF' in s:
            return s, 0
        m = re.search(r'^config BPF_SYSCALL\n', s, re.M)
        assert m, 'init/Kconfig 找不到 config BPF_SYSCALL'
        # 找到该 config 段结束（下一个顶层 config/menu/endmenu）
        m2 = re.search(r'^(config |menu|endmenu|source )', s[m.end():], re.M)
        end = m.end() + (m2.start() if m2 else 0)
        return s[:end] + KCONFIG_ENTRY + '\n' + s[end:], 1
    patch_file(p, f3, 'init/Kconfig += CONFIG_BPF_UNPRIV_DEFAULT_OFF')

    # ---- 4) kernel/bpf/syscall.c ----
    p = os.path.join(root, 'kernel/bpf/syscall.c')
    def f4(s):
        n = 0
        if 'IS_BUILTIN(CONFIG_BPF_UNPRIV_DEFAULT_OFF)' not in s:
            old = 'int sysctl_unprivileged_bpf_disabled __read_mostly;'
            assert old in s, 'syscall.c 找不到 sysctl_unprivileged_bpf_disabled'
            s = s.replace(old, old[:-1] + ' =\n \tIS_BUILTIN(CONFIG_BPF_UNPRIV_DEFAULT_OFF) ? 2 : 0;', 1)
            n += 1
        if 'bpf_obj_get_info_by_fd' not in s:
            m = re.search(r'^#endif /\* CONFIG_CGROUP_BPF \*/\n', s, re.M)
            assert m, 'syscall.c 找不到 CONFIG_CGROUP_BPF #endif 锚点'
            s = s[:m.end()] + SYSCALL_FUNCS + s[m.end():]
            n += 1
        # syscall 体内联 tail-zero → 调用 helper
        old_tail = '''	if (size > sizeof(attr)) {
		unsigned char __user *addr;
		unsigned char __user *end;
		unsigned char val;

		addr = (void __user *)uattr + sizeof(attr);
		end  = (void __user *)uattr + size;

		for (; addr < end; addr++) {
			err = get_user(val, addr);
			if (err)
				return err;
			if (val)
				return -E2BIG;
		}
		size = sizeof(attr);
	}
'''
        new_tail = '''	err = check_uarg_tail_zero(uattr, sizeof(attr), size);
	if (err)
		return err;
	size = min_t(u32, size, sizeof(attr));
'''
        if old_tail in s:
            s = s.replace(old_tail, new_tail, 1)
            n += 1
        if 'case BPF_OBJ_GET_INFO_BY_FD:' not in s:
            anchor = '''#endif

	default:
		err = -EINVAL;
		break;
	}
'''
            assert anchor in s, 'syscall.c 找不到 switch 的 default 锚点'
            s = s.replace(anchor, '#endif\n' + SYSCALL_CASE + '\n	default:\n		err = -EINVAL;\n		break;\n	}\n', 1)
            n += 1
        return s, n
    patch_file(p, f4, 'kernel/bpf/syscall.c += BPF_OBJ_GET_INFO_BY_FD 实现')

    # ---- 5) defconfig ----
    for dc in defconfigs:
        p = os.path.join(root, dc)
        if not os.path.exists(p):
            print(f'   ⚠️ {dc} 不存在，跳过'); continue
        def f5(s):
            if 'CONFIG_BPF_UNPRIV_DEFAULT_OFF' in s:
                return s, 0
            if 'CONFIG_BPF_SYSCALL=y' not in s:
                return s, 0
            return s.replace('CONFIG_BPF_SYSCALL=y\n',
                             'CONFIG_BPF_SYSCALL=y\nCONFIG_BPF_UNPRIV_DEFAULT_OFF=y\n', 1), 1
        patch_file(p, f5, f'{dc} += CONFIG_BPF_UNPRIV_DEFAULT_OFF=y')

    print('\n完成。')


if __name__ == '__main__':
    main()
