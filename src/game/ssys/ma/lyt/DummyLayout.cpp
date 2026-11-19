#include <game/ssys/ma/lyt/DummyLayout.hpp>

#pragma arm
bool ssys::ma::lyt::DummyLayout::BindAnimationAuto(const nw::lyt::AnimResource& animRes, nw::lyt::ResourceAccessor* resAcc)
{
    const unsigned short bindGroupNum = animRes.GetGroupNum();
    const unsigned short shareInfoNum = animRes.GetAnimationShareInfoNum();
    if(bindGroupNum == 0 || shareInfoNum != 0) return nw::lyt::Layout::BindAnimationAuto(animRes, resAcc);
    if(!GetRootPane()) return false;
    if(!animRes.GetResourceBlock()) return false;

    const nw::lyt::res::AnimationGroupRef* groupRefs = animRes.GetGroupArray();
    for(int groupIndex = 0; groupIndex < bindGroupNum; ++groupIndex)
    {
        nw::lyt::Group* group = GetGroupContainer()->FindGroupByName(groupRefs[groupIndex].GetName());
        const unsigned short animNum = animRes.CalcAnimationNum(group, animRes.IsDescendingBind());
        nw::lyt::AnimTransform* transform = nw::lyt::Layout::CreateAnimTransform();
        transform->SetResource(animRes.GetResourceBlock(), resAcc, animNum);
        nw::lyt::BindAnimation(group, transform, animRes.IsDescendingBind(), true);
    }

    return true;
}
