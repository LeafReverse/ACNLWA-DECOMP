#pragma once

namespace nw { namespace lyt { namespace res
{
    const unsigned int RESOURCETYPE_ANIMATION = 'anim';

    enum AnimTagFlag
    {
        ANIMTAGFLAG_DESCENDINGBIND = 1 << 0
    };

    struct DataBlockHeader
    {
        unsigned int kind;
        unsigned int size;
    };

    struct AnimationGroupRef
    {
        const char* GetName() const { return name; }

        char name[17];
        unsigned char flag;
        unsigned char padding[2];
    };

    struct AnimationTagBlock
    {
        DataBlockHeader blockHeader;
        unsigned short tagOrder;
        unsigned short groupNum;
        unsigned int nameOffset;
        unsigned int groupsOffset;
        short startFrame;
        short endFrame;
        unsigned char flag;
        unsigned char padding[3];
    };

    struct AnimationShareBlock
    {
        DataBlockHeader blockHeader;
        unsigned int animShareInfoOffset;
        unsigned short shareNum;
        unsigned char padding[2];
    };

    struct AnimationBlock
    {
        DataBlockHeader blockHeader;
        unsigned short frameSize;
        unsigned char loop;
        unsigned char padding;
        unsigned short fileNum;
        unsigned short animContNum;
        unsigned int animContOffsetsOffset;
    };
}}}
