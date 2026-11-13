#pragma once

namespace ssys { namespace st
{
    class ListNode
    {
        public:
        virtual ~ListNode();

        ListNode* prev;
        ListNode* next;
    };

    class List
    {
        public:
        List();
        virtual ~List();

        void Erase(ListNode* node);

        protected:
        ListNode* head;
        ListNode* tail;
    };
}}
