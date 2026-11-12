#pragma once

namespace nw { namespace lyt 
{
    class AnimTransform
    {
        public:
        virtual ~AnimTransform();

        void SetFrame(float value) { frame = value; }

        private:
        void* linkNext;
        void* linkPrev;
        const void* resource;
        float frame;
    };
}}
