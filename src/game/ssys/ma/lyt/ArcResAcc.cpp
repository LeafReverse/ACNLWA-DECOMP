#include <game/ssys/ma/lyt/ArcResAcc.hpp>
#include <sead/prim/SafeString.hpp>

#pragma arm
bool ssys::ma::lyt::ArcResAcc::LoadAllTextures()
{
    nw::lyt::ArcHandle handle;
    nw::lyt::ArcDir dir;
    nw::lyt::ArcDirEntry entry;

    nw::lyt::Arc::InitHandle(data, &handle);
    const wchar_t* rootDir = L"/";

    if(!nw::lyt::Arc::OpenResourceDir(&handle, rootDir, 'timg', &dir)) return false;

    sead::FixedSafeString<64> name;

    while(nw::lyt::Arc::ReadDirByExtension(&dir, L".bclim", 6, &entry))
    {
        if(entry.isDir) continue;

        name.convertFromWideCharString(sead::SafeStringBase<wchar_t>(entry.name));
        accessor.GetTexture(name.cstr());
    }

    return nw::lyt::Arc::CloseDir(&dir);
}
