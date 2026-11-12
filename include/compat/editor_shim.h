#ifndef CTR_DECOMP_EDITOR_SHIM_H
#define CTR_DECOMP_EDITOR_SHIM_H

#if !defined(__ARMCC_VERSION)

#define __svc(number)
#define __value_in_regs
#define __pure
#define __softfp
#define __irq
#define __forceinline inline __attribute__((always_inline))
#define __weak __attribute__((weak))
#define __packed __attribute__((packed))
#define __align(n) __attribute__((aligned(n)))
#define __declspec(x) __attribute__((x))
#define __int64 long long
#define __nop() __asm__ volatile("nop")

#endif
#endif
