#pragma once

class SaveData;

class SaveMgr
{
    public:
    static SaveData* GetSaveData();

    private:
    static SaveData* saveData;
};
