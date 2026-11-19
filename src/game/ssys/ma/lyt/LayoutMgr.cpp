#include <game/ssys/ma/lyt/LayoutMgr.hpp>

#pragma arm
ssys::ma::lyt::LayoutMgr* ssys::ma::lyt::LayoutMgr::Get()
{
    return s_Statics.instance;
}

ssys::ma::Allocator* ssys::ma::lyt::GetAllocator()
{
    return LayoutMgr::s_Statics.allocator;
}

ssys::ma::Allocator* ssys::ma::lyt::GetResAllocator()
{
    return LayoutMgr::s_Statics.resAllocator;
}

void ssys::ma::lyt::LayoutMgr::Register(Base2D* layout, bool isLower)
{
    switch(isLower)
    {
        case false:
            upperLayouts.Insert(layout);
            break;
        case true:
            lowerLayouts.Insert(layout);
            break;
    }
}
