/* Synthetic grader fixture. Not an instructor solution or a student submission.
 * Deliberately uses a private binary layout to exercise schema-independent cases. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>

typedef struct { int id; char title[48], author[48]; int year, count, available; } Book;
static Book books[128];
static int n;
static void read_db(void) {
    FILE *f = fopen("db.dat", "rb");
    n = f ? (int)fread(books, sizeof(Book), 128, f) : 0;
    if (f) fclose(f);
}
static void write_db(void) {
    FILE *f = fopen("db.dat", "wb");
    if (!f) exit(2);
    fwrite(books, sizeof(Book), n, f); fclose(f);
}
static void show(Book b) {
    printf("%d %s %s %d %d %s\n", b.id, b.title, b.author, b.year, b.count, b.available ? "True" : "False");
}
static int by_year(const void *a, const void *b) { return ((const Book *)b)->year - ((const Book *)a)->year; }
static int by_count(const void *a, const void *b) { return ((const Book *)b)->count - ((const Book *)a)->count; }

static int fixture_main(int argc, char **argv, const char *target) {
    if (!strcmp(target, "copy")) {
        if (argc != 4) return 1;
        FILE *in = fopen(argv[2], "rb");
        if (!in) { perror("error source"); return 1; }
        FILE *out = fopen(argv[3], "wb");
        if (!out) { perror("error destination"); fclose(in); return 2; }
        int ch, opt = atoi(argv[1]);
        while ((ch = fgetc(in)) != EOF) {
            if (opt == 1) ch = tolower((unsigned char)ch);
            if (opt == 2) ch = toupper((unsigned char)ch);
            fputc(ch, out); putchar(ch);
        }
        fclose(in); fclose(out); return 0;
    }
    if (!strcmp(target, "bookcreate") || !strcmp(target, "sortedbookcreate")) {
        n = 0;
        while (n < 128 && scanf("%d %47s %47s %d %d %d", &books[n].id, books[n].title,
            books[n].author, &books[n].year, &books[n].count, &books[n].available) == 6) n++;
        if (!strcmp(target, "sortedbookcreate")) qsort(books, n, sizeof(Book), by_year);
        write_db(); return 0;
    }
    read_db();
    if (!strcmp(target, "bookupdate")) {
        int op, id;
        if (scanf("%d%d", &op, &id) != 2) return 1;
        for (int i = 0; i < n; i++) if (books[i].id == id) {
            if (op == 0 && books[i].available) { books[i].count++; books[i].available = 0; }
            else if (op == 1) books[i].available = 1;
        }
        write_db(); return 0;
    }
    if (!strcmp(target, "searchbook")) {
        char name[48];
        if (scanf("%47s", name) != 1) return 1;
        for (int i = 0; i < n; i++) if (!strcmp(name, books[i].title)) { show(books[i]); return 0; }
        puts("not found"); return 0;
    }
    int option = 0;
    scanf("%d", &option);
    if (!strcmp(target, "sortedbookquery")) qsort(books, n, sizeof(Book), by_count);
    puts("id bookName author year numofborrow borrow");
    for (int i = 0; i < n; i++) if (!option || books[i].available) show(books[i]);
    return 0;
}
