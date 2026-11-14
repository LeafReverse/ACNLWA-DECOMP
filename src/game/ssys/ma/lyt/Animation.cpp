#include <game/ssys/ma/lyt/Animation.hpp>
#include <game/ssys/ma/lyt/FrameCtrl.hpp>
#include <nw/lyt/AnimTransform.hpp>
#include <nw/lyt/Layout.hpp>

struct ssys::ma::lyt::Animation::EntryInfo
{
};

#pragma arm
ssys::ma::lyt::Animation::Animation() : isBound(0), entryCount(0), entries(0), isDescendingBind(false) {}

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

void ssys::ma::lyt::FrameCtrl::Update()
{
    prevFrame = frame;
    float next;
    if(flags & FLAG_REVERSE)
    {
        if(frameIncrease <= frame)
            next = frame - frameIncrease;
        else if(flags & FLAG_ONE_SHOT)
            next = 0.0f;
        else
            next = frameCount - frameIncrease + frame;
    }
    else
    {
        next = frameIncrease + frame;
        if(flags & FLAG_ONE_SHOT)
        {
            if(next > frameCount - 1.0f) next = frameCount - 1.0f;
        }
        else if(next >= frameCount)
            next -= frameCount;
    }

    ApplyFrame(next);
}

void ssys::ma::lyt::FrameCtrl::SetAnimTransform(nw::lyt::AnimTransform* transform)
{
    animTransform = transform;
    if(!animTransform) return;

    bool isOneShot = true;
    if(animTransform->IsLoopData()) isOneShot = false;

    Reset(animTransform->GetFrameSize(), 1.0f, 0.0f, isOneShot);
    if(!animTransform) return;

    animTransform->SetFrame(frame);
}

void ssys::ma::lyt::FrameCtrl::SetFrame(float value)
{
    prevFrame = value;
    ApplyFrame(value);
}

void ssys::ma::lyt::FrameCtrl::Init(float count, float increase, float start, bool isOneShot)
{
    frameCount = count;
    frame = (start < 0.0f) ? 0.0f : start;
    frameIncrease = increase;
    flags = isOneShot;
    prevFrame = frame;
}

void ssys::ma::lyt::FrameCtrl::Setup(float count, float increase, float start, bool isOneShot)
{
    Init(count, increase, start, isOneShot);
    if(!animTransform) return;

    animTransform->SetFrame(frame);
}
