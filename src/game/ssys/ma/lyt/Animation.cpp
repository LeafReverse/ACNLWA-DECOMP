#include <game/ssys/ma/lyt/Animation.hpp>
#include <game/ssys/ma/lyt/FrameCtrl.hpp>
#include <nw/lyt/AnimTransform.hpp>
#include <nw/lyt/Layout.hpp>

struct ssys::ma::lyt::Animation::EntryInfo
{
};

#pragma arm
ssys::ma::lyt::Animation::Animation() : isBound(0), entryCount(0), entries(0), isDescendingBind(false) {}

ssys::ma::lyt::FrameCtrl::~FrameCtrl() {}

ssys::ma::lyt::Animation::~Animation()
{
    Animation* self = this;
    if(!self->animTransform) return;

    animTransform->~AnimTransform();
    nw::lyt::Layout::FreeMemory(animTransform);
    animTransform = 0;
    delete[] entries;
    entries = 0;
}

void ssys::ma::lyt::FrameCtrl::SetFrame(float value)
{
    prevFrame = value;
    frame = value;
    if(!animTransform) return;

    animTransform->SetFrame(value);
}

void ssys::ma::lyt::FrameCtrl::Setup(float count, float increase, float start, bool isLoop)
{
    frameCount = count;
    frame = (start < 0.0f) ? 0.0f : start;
    frameIncrease = increase;
    loop = isLoop;
    FrameCtrl::SetFrame(frame);
}
