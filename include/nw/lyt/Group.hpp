#pragma once

#include <nw/lyt/Pane.hpp>
#include <nw/ut/LinkList.hpp>

namespace nw { namespace lyt 
{
    struct PaneLink : ut::LinkListNode
    {
        Pane* target;
    };

    class Group
    {
        public:
        virtual ~Group();

        const ut::LinkList& GetPaneList() const 
        { 
            return paneList; 
        }

        private:
        ut::LinkListNode link;
        ut::LinkList paneList;
    };

    class GroupContainer
    {
        public:
        Group* FindGroupByName(const char* name);
    };
}}
