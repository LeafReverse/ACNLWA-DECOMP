#pragma once

#include <nw/ut/RuntimeTypeInfo.hpp>

namespace nw { namespace lyt 
{
    class AnimTransform;

    class Pane
    {
        public:
        virtual ~Pane();
        virtual const ut::internal::RuntimeTypeInfo* GetRuntimeTypeInfo() const;
        virtual void vfunc_3();
        virtual void vfunc_4();
        virtual void vfunc_5();
        virtual void vfunc_6();
        virtual void vfunc_7();
        virtual void vfunc_8();
        virtual void vfunc_9();
        virtual void vfunc_10();
        virtual Pane* FindPaneByName(const char* name, bool recursive = true);
        virtual void vfunc_12();
        virtual void vfunc_13();
        virtual void vfunc_14();
        virtual void BindAnimation(AnimTransform* animTransform, bool recursive = true, bool disable = false);
        virtual void UnbindAnimation(AnimTransform* animTransform, bool recursive = true);
    };

    class TextBox : public Pane
    {
        public:
        static const ut::internal::RuntimeTypeInfo typeInfo;
    };

    class Picture : public Pane
    {
        public:
        static const ut::internal::RuntimeTypeInfo typeInfo;
    };
}}
