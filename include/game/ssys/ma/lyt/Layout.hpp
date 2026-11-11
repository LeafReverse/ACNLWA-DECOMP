#pragma once

#include <game/ssys/ma/lyt/Animation.hpp>
#include <nw/lyt/Group.hpp>
#include <nw/lyt/Layout.hpp>

namespace ssys { namespace ma { namespace lyt 
{
    class Layout
    {
        public:
        virtual ~Layout();

        void BindAnimation(Animation* animation, const nw::lyt::Group* group, bool recursive);
        void UnbindAnimation(Animation* animation, const nw::lyt::Group* group, bool recursive);
        void UnbindAnimation(Animation* animation);
        void UnbindAllAnimation();
        nw::lyt::Pane* FindPane(const char* name);
        nw::lyt::Group* FindGroup(const char* name);
        nw::lyt::Picture* FindPicture(const char* name);
        nw::lyt::TextBox* FindTextBox(const char* name);

        private:
        unsigned char unk4[0xC];
        nw::lyt::Layout layout;
    };
}}}
