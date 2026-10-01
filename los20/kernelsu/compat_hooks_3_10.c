// SPDX-License-Identifier: GPL-2.0
/*
 * [zerofltectc] 3.10 兼容桩
 *
 * 本内核（3.10.108, Exynos7420）里已经被**旧版 KernelSU**（bmax121 12126 时代）
 * 打了「手工 hook」补丁 —— 在 security/security.c、drivers/input/input.c、
 * fs/read_write.c、security/selinux/hooks.c 里直接调用 ksu_* 函数。
 * 提交：6946f20fcb4 "KernelSU: manual security hooks"
 *       3a82639b407 "KernelSU: scope-minimized manual hooks - k3.10 v1.5"
 *
 * 新版 KernelSU（backslashxx, KSU_VERSION=32651）**不再需要这些调用点** ——
 * 它自己做动态 hook（syscall 表改写 / kprobes / LSM 函数指针劫持 / kallsyms 搜索），
 * 见 drivers/kernelsu/kernel/INTERNAL.md：
 *   "wired up for aarch64 and armeabi, k3.0 ~ mainline"
 *   "3.x LSM scans the whole kernel to hunt for selinux_ops"
 *
 * 所以这里给旧调用点提供**空实现**，让内核能链接通过，
 * 这些调用变成 no-op，实际 hook 由新驱动自己完成。
 */

int ksu_handle_prctl(int option, unsigned long arg2, unsigned long arg3,
		     unsigned long arg4, unsigned long arg5)
{
	return 0;
}

int ksu_handle_rename(struct dentry *old_dentry, struct dentry *new_dentry)
{
	return 0;
}

int ksu_handle_setuid(struct cred *new, const struct cred *old)
{
	return 0;
}

int ksu_key_permission(key_ref_t key_ref, const struct cred *cred, unsigned perm)
{
	return 0;
}

int ksu_inode_permission(struct inode *inode, int mask)
{
	return 0;
}

int ksu_handle_input_handle_event(unsigned int *type, unsigned int *code, int *value)
{
	return 0;
}

int ksu_handle_sys_read(unsigned int fd, char __user **buf_ptr, size_t *count_ptr)
{
	return 0;
}

bool is_ksu_transition(const struct task_security_struct *old_tsec,
		       const struct task_security_struct *new_tsec)
{
	return false;
}
