#pragma once

#include <game/ssys/ma/lyt/FrameCtrl.hpp>

namespace ssys { namespace ma { namespace lyt 
{
    class Layout;

    class Animation : public FrameCtrl
    {
        public:
        Animation();
        virtual ~Animation();

        private:
        friend class Layout;

        struct EntryInfo;

        unsigned char isBound;
        unsigned short entryCount;
        EntryInfo* entries;
        bool isDescendingBind;
    };
}}}
