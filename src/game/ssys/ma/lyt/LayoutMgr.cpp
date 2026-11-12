#include <game/ssys/ma/lyt/LayoutMgr.hpp>

#pragma arm
ssys::ma::lyt::LayoutMgr* ssys::ma::lyt::LayoutMgr::Get()
{
    return s_pInstance;
}
