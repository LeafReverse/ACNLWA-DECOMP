#pragma once

#include <game/ssys/ma/lyt/FrameCtrl.hpp>

namespace ssys { namespace ma { namespace lyt 
{
    class Layout;
    class ResAccInterface;

    class Animation : public FrameCtrl
    {
        public:
        Animation();
        virtual ~Animation();

        bool Initialize(const char* name, const ResAccInterface* resAcc);

        private:
        friend class Layout;

        unsigned char isBound;
        unsigned short entryCount;
        nw::lyt::AnimationLink* entries;
        bool isDescendingBind;
    };
}}}
