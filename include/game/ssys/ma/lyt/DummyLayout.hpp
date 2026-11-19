#pragma once

#include <nw/lyt/Layout.hpp>

namespace ssys { namespace ma { namespace lyt
{
    class DummyLayout : public nw::lyt::Layout
    {
        public:
        virtual nw::lyt::AnimTransform* CreateAnimTransform(const void* animResBuf, nw::lyt::ResourceAccessor* resAcc)
        {
            nw::lyt::AnimTransform* transform = nw::lyt::Layout::CreateAnimTransform(animResBuf, resAcc);
            if(transform)
            {
                nw::ut::LinkList& transforms = GetAnimTransformList();
                transforms.erase(transform->GetLink());
            }

            return transform;
        }

        virtual bool BindAnimationAuto(const nw::lyt::AnimResource& animRes, nw::lyt::ResourceAccessor* resAcc);
    };
}}}
