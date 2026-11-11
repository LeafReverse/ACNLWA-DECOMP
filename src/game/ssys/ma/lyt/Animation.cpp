#include <game/ssys/ma/lyt/Animation.hpp>
#include <game/ssys/ma/lyt/FrameCtrl.hpp>

#pragma arm
ssys::ma::lyt::Animation::Animation() : isBound(0), entryCount(0), entries(0), isDescendingBind(false) {}

void ssys::ma::lyt::FrameCtrl::SetFrame(float value)
{
    prevFrame = value;
    frame = value;
    if(!animTransform) return;

    animTransform->SetFrame(value);
}
