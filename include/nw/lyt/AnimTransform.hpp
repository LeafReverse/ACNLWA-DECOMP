#pragma once

#include <nw/lyt/Resources.hpp>
#include <nw/ut/LinkList.hpp>

namespace nw { namespace lyt 
{
    class Group;
    class Material;
    class Pane;
    class ResourceAccessor;

    class AnimTransform
    {
        public:
        virtual ~AnimTransform();
        virtual void Animate(unsigned int idx, Pane* pane) = 0;
        virtual void Animate(unsigned int idx, Material* material) = 0;
        virtual void SetResource(const res::AnimationBlock* block, ResourceAccessor* resAcc) = 0;
        virtual void SetResource(const res::AnimationBlock* block, ResourceAccessor* resAcc, unsigned short animNum) = 0;

        unsigned short GetFrameSize() const;
        bool IsLoopData() const;
        void SetFrame(float value) { frame = value; }
        const res::AnimationBlock* GetResource() const { return resource; }
        ut::LinkListNode* GetLink() { return &link; }

        private:
        ut::LinkListNode link;
        const res::AnimationBlock* resource;
        float frame;
    };

    class AnimationLink
    {
        public:
        AnimationLink();

        private:
        ut::LinkListNode link;
        AnimTransform* animTrans;
        unsigned short idx;
        bool isDisable;
    };

    void BindAnimation(Group* group, AnimTransform* animTransform, bool isRecursive, bool isDisabled);

    class AnimResource
    {
        public:
        explicit AnimResource(const void* animResBuf) { Set(animResBuf); }

        void Set(const void* animResBuf);
        bool IsDescendingBind() const;
        unsigned short GetGroupNum() const;
        const res::AnimationGroupRef* GetGroupArray() const;
        unsigned short CalcAnimationNum(Group* group, bool isRecursive) const;
        unsigned short GetAnimationShareInfoNum() const;
        const res::AnimationBlock* GetResourceBlock() const { return resBlock; }

        private:
        const void* fileHeader;
        const res::AnimationBlock* resBlock;
        const res::AnimationTagBlock* tagBlock;
        const res::AnimationShareBlock* shareBlock;
    };
}}
