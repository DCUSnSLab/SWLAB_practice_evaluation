#include <unistd.h>
#include <fcntl.h>
int main(int argc,char **argv){if(argc!=3)return 1;int in=open(argv[1],O_RDONLY),out=open(argv[2],O_WRONLY|O_CREAT|O_TRUNC,0600);if(in<0||out<0)return 1;char b[512];ssize_t n;while((n=read(in,b,sizeof b))>0){ssize_t p=0;while(p<n){ssize_t w=write(out,b+p,n-p);if(w<=0)return 1;p+=w;}}close(in);close(out);return n<0;}
