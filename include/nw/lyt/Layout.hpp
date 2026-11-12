#pragma once

#include <nw/lyt/Group.hpp>
#include <nw/lyt/Pane.hpp>

namespace nw { namespace lyt 
{
    class Layout
    {
        public:
        virtual ~Layout();
        virtual void vfunc_2();
        virtual void vfunc_3();
        virtual void vfunc_4();
        virtual void vfunc_5();
        virtual void vfunc_6();
        virtual void vfunc_7();
        virtual void UnbindAnimation(AnimTransform* animTransform);
        virtual void UnbindAllAnimation();

        Pane* GetRootPane() const 
        { 
            return rootPane; 
        }

        GroupContainer* GetGroupContainer() const 
        { 
            return groupContainer; 
        }

        private:
        unsigned int animTransCount;
        void* animTransNext;
        void* animTransPrev;
        Pane* rootPane;
        GroupContainer* groupContainer;
    };
}}
