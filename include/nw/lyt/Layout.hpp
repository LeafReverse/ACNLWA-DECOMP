#pragma once

#include <nw/lyt/AnimTransform.hpp>
#include <nw/lyt/Group.hpp>
#include <nw/lyt/Pane.hpp>
#include <nw/lyt/ResourceAccessor.hpp>

namespace nw { namespace lyt 
{
    class DrawInfo;
    class TagProcessor;

    class Layout
    {
        public:
        Layout();
        virtual ~Layout();

        static void FreeMemory(void* ptr);
        virtual bool Build(const void* lytResBuf, ResourceAccessor* resAcc);
        virtual AnimTransform* CreateAnimTransform();
        virtual AnimTransform* CreateAnimTransform(const void* animResBuf, ResourceAccessor* resAcc);
        virtual AnimTransform* CreateAnimTransform(const AnimResource& animRes, ResourceAccessor* resAcc);
        virtual void DeleteAnimTransform(AnimTransform* animTransform);
        virtual void BindAnimation(AnimTransform* animTransform);
        virtual void UnbindAnimation(AnimTransform* animTransform);
        virtual void UnbindAllAnimation();
        virtual bool BindAnimationAuto(const AnimResource& animRes, ResourceAccessor* resAcc);
        virtual void SetAnimationEnable(AnimTransform* animTransform, bool isEnabled);
        virtual void CalculateMtx(const DrawInfo& drawInfo);
        virtual void Draw(const DrawInfo& drawInfo);
        virtual void Animate(unsigned int option = 0);
        virtual void SetTagProcessor(TagProcessor* tagProcessor);

        Pane* GetRootPane() const 
        { 
            return rootPane; 
        }

        GroupContainer* GetGroupContainer() const 
        { 
            return groupContainer; 
        }

        ut::LinkList& GetAnimTransformList()
        {
            return animTransList;
        }

        protected:
        virtual Pane* BuildPaneObj(unsigned int kind, const void* block, const void* resBlockSet);

        private:
        ut::LinkList animTransList;
        Pane* rootPane;
        GroupContainer* groupContainer;
        float width;
        float height;
    };
}}
