#pragma once

#include <game/ssys/st/List.hpp>
#include <nw/lyt/ResourceAccessor.hpp>

namespace ssys { namespace ma { namespace lyt
{
    class ResAccInterface
    {
        public:
        virtual ~ResAccInterface();

        protected:
        nw::lyt::ResourceAccessor* resourceAccessor;
    };

    class TexBufList : public st::List
    {
        public:
        virtual ~TexBufList();
    };

    class ArcResourceAccessorVRAM : public nw::lyt::ArcResourceAccessor
    {
        public:
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

        bool SetData(const void* data, const char* rootDir);
        bool LoadAllTextures();

        private:
        const void* data;
        ArcResourceAccessorVRAM accessor;
    };
}}}
