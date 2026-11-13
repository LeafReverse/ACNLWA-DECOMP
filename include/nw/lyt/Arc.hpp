#pragma once

namespace nw { namespace lyt
{
    struct ArcHandle
    {
        const void* archive;
        const void* fstStart;
        const void* fileStart;
        unsigned int entryNum;
        const wchar_t* fstStringStart;
        unsigned int fstLength;
        unsigned int currentDir;
    };

    struct ArcDir
    {
        ArcHandle* handle;
        unsigned int entryNum;
        unsigned int location;
        unsigned int next;
    };

    struct ArcDirEntry
    {
        ArcHandle* handle;
        unsigned int entryNum;
        const wchar_t* name;
        bool isDir;
    };

    class Arc
    {
        public:
        static bool InitHandle(const void* archive, ArcHandle* handle);
        static bool OpenResourceDir(ArcHandle* handle, const wchar_t* rootDir, unsigned int resType, ArcDir* dir);
        static bool ReadDirByExtension(ArcDir* dir, const wchar_t* extension, unsigned int extensionLength, ArcDirEntry* entry);
        static bool CloseDir(ArcDir* dir);
    };
}}
