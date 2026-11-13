#pragma once

#include <nw/lyt/Arc.hpp>
#include <nw/ut/LinkList.hpp>

namespace nw { namespace font
{
    class Font;
}}

namespace nw { namespace lyt
{
    typedef unsigned int ResType;

    struct TextureInfo
    {
        unsigned int texObject;
        unsigned int physicalAddress;
        unsigned short width;
        unsigned short height;
        unsigned short realWidth;
        unsigned short realHeight;
        unsigned int format;
    };

    class ResourceAccessor
    {
        public:
        virtual ~ResourceAccessor();
        virtual void* GetResource(ResType resType, const char* name, unsigned int* size = 0) = 0;
        virtual font::Font* GetFont(const char* name) = 0;
        virtual TextureInfo GetTexture(const char* name) = 0;
        virtual TextureInfo LoadTexture(const char* name);
        virtual font::Font* LoadFont(const char* name);
    };

    class ArcResourceAccessor : public ResourceAccessor
    {
        public:
        virtual ~ArcResourceAccessor();
        virtual void* GetResource(ResType resType, const char* name, unsigned int* size = 0);
        virtual font::Font* GetFont(const char* name);
        virtual TextureInfo GetTexture(const char* name);

        bool Attach(void* archive, const char* rootDir);
        void RegistFont(const char* name, const font::Font* font);

        private:
        ArcHandle arcHandle;
        void* arcBuf;
        ut::LinkList fontList;
        ut::LinkList textureList;
        wchar_t resRootDir[64];
        wchar_t resName[64];
    };
}}
