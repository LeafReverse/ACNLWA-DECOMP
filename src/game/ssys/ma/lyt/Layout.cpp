#include <game/ssys/ma/lyt/Layout.hpp>

#pragma arm
void ssys::ma::lyt::Layout::BindAnimation(Animation* animation, const nw::lyt::Group* group, bool recursive)
{
    animation->isBound = true;
    const nw::ut::LinkList* panes = &group->GetPaneList();
    nw::ut::LinkList::ConstIterator it = panes->GetBeginIter();
    if(it == panes->GetEndIter()) return;

    do
    {
        static_cast<const nw::lyt::PaneLink&>(*it).target->BindAnimation(animation->GetAnimTransform(), recursive, false);
        ++it;
    }
    while(it != panes->GetEndIter());
}

nw::lyt::Pane* ssys::ma::lyt::Layout::FindPane(const char* name)
{
    return layout.GetRootPane()->FindPaneByName(name);
}

void ssys::ma::lyt::Layout::UnbindAnimation(Animation* animation, const nw::lyt::Group* group, bool recursive)
{
    animation->isBound = false;
    const nw::ut::LinkList* panes = &group->GetPaneList();
    nw::ut::LinkList::ConstIterator it = panes->GetBeginIter();
    if(it == panes->GetEndIter()) return;

    do
    {
        static_cast<const nw::lyt::PaneLink&>(*it).target->UnbindAnimation(animation->GetAnimTransform(), recursive);
        ++it;
    }
    while(it != panes->GetEndIter());
}

nw::lyt::Picture* ssys::ma::lyt::Layout::FindPicture(const char* name)
{
    return nw::ut::DynamicCast<nw::lyt::Picture>(FindPane(name));
}

nw::lyt::TextBox* ssys::ma::lyt::Layout::FindTextBox(const char* name)
{
    return nw::ut::DynamicCast<nw::lyt::TextBox>(FindPane(name));
}

void ssys::ma::lyt::Layout::UnbindAnimation(Animation* animation)
{
    animation->isBound = false;
    layout.UnbindAnimation(animation->GetAnimTransform());
}

nw::lyt::Group* ssys::ma::lyt::Layout::FindGroup(const char* name)
{
    return layout.GetGroupContainer()->FindGroupByName(name);
}

void ssys::ma::lyt::Layout::UnbindAllAnimation()
{
    layout.nw::lyt::Layout::UnbindAllAnimation();
}
