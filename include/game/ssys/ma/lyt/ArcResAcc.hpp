#pragma once

#include <game/ssys/st/List.hpp>
#include <nw/lyt/ResourceAccessor.hpp>

namespace ssys { namespace ma { namespace lyt
{
    class ResAccInterface
    {
        public:
        ResAccInterface(nw::lyt::ResourceAccessor* accessor) : resourceAccessor(accessor), data(0) {}
        virtual ~ResAccInterface() {}

        protected:
        nw::lyt::ResourceAccessor* resourceAccessor;
        const void* data;
    };

    class TexBufList : public st::List
    {
        public:
        TexBufList() {}
        virtual ~TexBufList();
    };

    class ArcResourceAccessorVRAM : public nw::lyt::ArcResourceAccessor
    {
        public:
        ArcResourceAccessorVRAM() : textureArea(0x2010000) {}
        virtual ~ArcResourceAccessorVRAM();
        virtual nw::lyt::TextureInfo LoadTexture(const char* name);

        private:
        unsigned int textureArea;
        TexBufList texBufList;
    };

    class ArcResAcc : public ResAccInterface
    {
        public:
        ArcResAcc();
        virtual ~ArcResAcc();

        bool SetData(const void* archive, const char* rootDir);
        bool LoadAllTextures();

        private:
        ArcResourceAccessorVRAM accessor;
    };
}}}
