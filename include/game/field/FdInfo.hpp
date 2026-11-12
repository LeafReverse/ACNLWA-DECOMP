#pragma once

class Field;

class FdInfo
{
    public:
    static Field* GetCurrentField();

    private:
    static Field* s_pCurrentField;
};
