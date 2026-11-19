#include <game/ssys/ma/lyt/Animation.hpp>
#include <game/ssys/ma/lyt/ArcResAcc.hpp>
#include <game/ssys/ma/lyt/DummyLayout.hpp>
#include <game/ssys/ma/lyt/LayoutMgr.hpp>
#include <nw/lyt/AnimTransform.hpp>
#include <nw/lyt/Layout.hpp>
#include <sead/basis/New.hpp>

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

bool ssys::ma::lyt::Animation::Initialize(const char* name, const ResAccInterface* resAcc)
{
    if(animTransform)
    {
        animTransform->~AnimTransform();
        nw::lyt::Layout::FreeMemory(animTransform);
        animTransform = 0;
        delete[] entries;
        entries = 0;
    }

    static DummyLayout s_DummyLayout;

    void* resource = resAcc->GetResourceAccessor()->GetResource(nw::lyt::res::RESOURCETYPE_ANIMATION, name);
    if(!resource) resource = resAcc->GetResourceAccessor()->GetResource(0, name);

    nw::lyt::AnimTransform* transform = s_DummyLayout.CreateAnimTransform(resource, resAcc->GetResourceAccessor());
    if(!transform) return false;

    nw::lyt::AnimResource animRes(resource);
    isDescendingBind = animRes.IsDescendingBind();
    entryCount = transform->GetResource()->animContNum;
    entries = new(GetAllocator()->GetHeap(), 4) nw::lyt::AnimationLink[entryCount];
    SetAnimTransform(transform);

    return true;
}
