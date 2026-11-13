#pragma once

#include <nw/lyt/AnimTransform.hpp>

namespace ssys { namespace ma { namespace lyt 
{
    class FrameCtrl
    {
        public:
        FrameCtrl() : frameCount(0.0f), frame(0.0f), prevFrame(0.0f), frameIncrease(1.0f), loop(0), animTransform(0) {}

        virtual ~FrameCtrl() {}
        virtual void SetFrame(float value);

        void Setup(float count, float increase, float start, bool isLoop);
        void Init(float count, float increase, float start, bool isLoop);

        nw::lyt::AnimTransform* GetAnimTransform() const { return animTransform; }

        protected:
        float frameCount;
        float frame;
        float prevFrame;
        float frameIncrease;
        unsigned char loop;
        nw::lyt::AnimTransform* animTransform;
    };
}}}
