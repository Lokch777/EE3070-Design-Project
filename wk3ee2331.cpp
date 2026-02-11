#include <iostream>
#include <fstream>


using namespace std;

struct ListNode {
	int info;
	ListNode* link;
};

int CountPositive(ListNode* head) 
{
	int count = 0;
	ListNode* cur = head;
	while (cur != NULL) {
		if (cur->info > 0) {
			count++;
		}
		cur = cur->link;
	}
	return count;
}

void insert(ListNode*& head, int x) {
	ListNode* p = new ListNode;
	p->info = x;
	p->link = NULL;

		if (head == NULL || x <= head->info) {
			p->link = head;
			head = p;
		}
		else {
			ListNode* prev = head;
			ListNode* cur = head->link;

			while (cur != NULL && x > cur->info) {
				prev = cur;
				cur = cur->link;
			}

			p->link = prev->link;
			prev->link = p;
		}
}

int main() {
	ListNode* head = NULL;
	ifstream inFile("data1.txt");

	if (!inFile.is_open()) {
		cout << "Error: cannot open data file" << endl;
		return 1;
	}
	while (!inFile.eof()) {
		int i;
		inFile >> i;

		if (!inFile.fail())
			insert(head, i);
		else
			break;
	}
	inFile.close();

	int positiveCount = CountPositive(head);
	cout << "The number of positive elements is " << positiveCount << "." << endl;




}