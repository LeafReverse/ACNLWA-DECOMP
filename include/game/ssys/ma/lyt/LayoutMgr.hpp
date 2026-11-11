#pragma once

namespace ssys { namespace ma { namespace lyt 
{
    class LayoutMgr
    {
        public:
        static LayoutMgr* Get();

        private:
        static LayoutMgr* s_pInstance;
    };
}}}
