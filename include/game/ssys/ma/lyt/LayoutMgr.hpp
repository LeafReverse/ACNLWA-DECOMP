#pragma once

#include <game/ssys/ma/Allocator.hpp>
#include <game/ssys/ma/lyt/LayoutList.hpp>

namespace ssys { namespace ma { namespace lyt 
{
    Allocator* GetAllocator();
    Allocator* GetResAllocator();

    class LayoutMgr
    {
        public:
        virtual ~LayoutMgr();

        static LayoutMgr* Get();

        void Register(Base2D* layout, bool isLower);

        private:
        friend Allocator* GetAllocator();
        friend Allocator* GetResAllocator();

        struct Statics
        {
            LayoutMgr* instance;
            Allocator* allocator;
            Allocator* resAllocator;
        };

        static Statics s_Statics;

        LayoutList upperLayouts;
        LayoutList lowerLayouts;
    };
}}}
