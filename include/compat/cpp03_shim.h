#ifndef CTR_DECOMP_CPP03_SHIM_H
#define CTR_DECOMP_CPP03_SHIM_H

#if defined(__ARMCC_VERSION) && defined(__cplusplus)

#define override
#define final

namespace ctr_decomp_shim 
{
    class nullptr_t 
    {
        public:
        template <class T> operator T*() const { return 0; }
        template <class C, class T> operator T C::*() const { return 0; }

        private:
        void operator&() const;
    };
}

static const ctr_decomp_shim::nullptr_t nullptr = {};

#endif
#endif
