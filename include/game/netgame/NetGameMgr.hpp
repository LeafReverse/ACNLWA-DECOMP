#pragma once

namespace netgame 
{
    enum Type
    {
        TYPE_NONE,
        TYPE_FRIEND_MATCH,
        TYPE_RANDOM_MATCH,
        TYPE_DREAM
    };

    enum PlayerNo
    {
        PLAYER_NO_HOST = 0,
        PLAYER_NO_0 = 0,
        PLAYER_NO_1 = 1,
        PLAYER_NO_2 = 2,
        PLAYER_NO_3 = 3,
        PLAYER_NO_INVALID = 4,
        PLAYER_NO_MY_NO = 4,
        PLAYER_NO_TARGET_ALL = 4,
        PLAYER_NO_MAX_PLAYER_COUNT = 4
    };

    Type GetNetgameType();

    class NetGameMgr
    {
        public:
        static NetGameMgr* Get() { return s_pInstance; }

        PlayerNo GetMyPlayerNo() const;

        private:
        friend Type GetNetgameType();

        unsigned char unk0[0x13268];
        unsigned char myPlayerNo;
        unsigned char unk13269[0x34];
        unsigned char netgameType;
        unsigned char unk1329E[0xE];
        bool isInNetSession;
        bool isInNetgame;
        bool isPlayerAssigned;

        static NetGameMgr* s_pInstance;
    };
}
