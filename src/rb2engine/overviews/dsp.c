/* Independent implementation of measured/recovered signal processing facts.
   No vendor code is linked or executed. Outputs float block features only. */
#include <math.h>
#include <stdint.h>
#include <stddef.h>

typedef struct { float b, a1, a2, x1, x2, y1, y2; } Band;
#define OVERVIEW_READ_FRAMES 16384
static Band make_band(float fs, float f, float bw) {
    float w = (float)(2.0 * 3.14159265358979323846) * f / fs;
    float s = sinf(w), c = cosf(w);
    float alpha = s*sinhf((float)(log(2.0)/2.0)*bw*w/s);
    Band b = {alpha/(1+alpha), -2*c/(1+alpha), (1-alpha)/(1+alpha),0,0,0,0};
    return b;
}
static float process_fma(Band *b, float x) {
    float p=-b->a1*b->y1;
    float y=fmaf(b->b,x-b->x2,p);
    y=fmaf(-b->a2,b->y2,y);
    b->x2=b->x1;b->x1=x;b->y2=b->y1;b->y1=y;
    return y;
}

/* The native nine-band bank vectorizes bands 0..7. Its rounding order differs
   from the scalar ninth band and the scalar RGB bank; preserve that order. */
static float process_vector_order(Band *b, float x) {
    float y=b->b*(x-b->x2);
    y=fmaf(-b->a1,b->y1,y);
    y=fmaf(-b->a2,b->y2,y);
    b->x2=b->x1;b->x1=x;b->y2=b->y1;b->y1=y;
    return y;
}

/* Database RGB overview has a separate accumulator from deck waveform data.
   Each 16,384-frame read restarts its 70-frame segmentation. Filter state
   continues across reads. Finalize BEFORE merging the current short segment. */
int64_t rgb_overview_blocks(const float *pcm,int64_t frames,int channels,int rate,
                           int64_t declared_frames,int64_t timestamp_offset,
                           float *out,int64_t capacity) {
    if(!pcm||!out||frames<=0||declared_frames<frames||channels<1||channels>2||rate<16000)return -1;
    int substep=(int)fmaf(1.5873016119003296f*.001f,(float)rate,.5f);
    int step=substep*6;
    int64_t count=declared_frames/step+1, done=0;
    if(capacity<count)return -2;
    const float freq[3]={88.f,990.f,7920.f},bw[3]={4.f,3.f,3.f};
    Band first[3],second[3];
    float envelope[3]={0},accum[3]={0},peak=0;
    float alpha=-expm1f(-1000.f/(10.f*((float)rate/step)));
    for(int k=0;k<3;k++){first[k]=make_band(rate,freq[k],bw[k]);second[k]=first[k];}
    for(int64_t pos=0;pos<frames;) {
        int64_t end=pos+substep;
        int64_t outer=(pos/OVERVIEW_READ_FRAMES+1)*OVERVIEW_READ_FRAMES;
        if(end>outer)end=outer;
        if(end>frames)end=frames;
        float next[3]={0},next_peak=0;
        for(int64_t i=pos;i<end;i++) {
            float x=pcm[i*channels];
            if(channels==2)x=(x+pcm[i*channels+1])*.5f;
            next_peak=fmaxf(next_peak,fabsf(x));
            for(int k=0;k<3;k++){
                float y=process_fma(&first[k],x);
                y=process_fma(&second[k],y);
                next[k]=fmaxf(next[k],fabsf(y));
            }
        }
        if(end+timestamp_offset>=step*(done+1)) {
            float sum=0;
            for(int k=0;k<3;k++){
                envelope[k]=accum[k]>=envelope[k]?accum[k]:fmaf(alpha,accum[k]-envelope[k],envelope[k]);
                sum+=envelope[k];accum[k]=0;
            }
            float factor=sum>0?peak/sum:0;
            for(int k=0;k<3;k++)out[done*3+k]=envelope[k]*factor;
            done++;peak=0;
        }
        for(int k=0;k<3;k++)accum[k]=fmaxf(accum[k],fminf(next[k],1.f));
        peak=fmaxf(peak,fminf(next_peak,1.f));
        pos=end;
    }
    while(done<count){
        float sum=0;
        for(int k=0;k<3;k++){
            envelope[k]=accum[k]>=envelope[k]?accum[k]:fmaf(alpha,accum[k]-envelope[k],envelope[k]);
            sum+=envelope[k];accum[k]=0;
        }
        float factor=sum>0?peak/sum:0;
        for(int k=0;k<3;k++)out[done*3+k]=envelope[k]*factor;
        done++;peak=0;
    }
    return done;
}

/* Classic database overview consumes nine 1-octave band RMS features, six
   short frames at a time. Band 6 is disabled in the observed 0x1bf mask. */
int64_t tri_overview_blocks(const float *pcm,int64_t frames,int channels,int rate,
                           int64_t declared_frames,int64_t timestamp_offset,
                           float *out,int64_t capacity) {
    if(!pcm||!out||frames<=0||declared_frames<frames||channels<1||channels>2||rate<16000)return -1;
    int substep=(int)fmaf(1.5873016119003296f*.001f,(float)rate,.5f);
    int step=substep*6;
    int64_t count=declared_frames/step+1,done=0;
    if(capacity<count)return -2;
    const float frequency[9]={32.5f,65.f,130.f,259.9f,519.8f,1039.7f,2079.4f,4158.7f,8317.5f};
    Band filters[9];
    for(int k=0;k<9;k++)filters[k]=make_band(rate,frequency[k],1.f);
    const float release[3]={72.5f,50.f,10.f};
    float envelope[3]={0},accum[3]={0},alpha[3];
    for(int k=0;k<3;k++)alpha[k]=-expm1f(-1000.f/(release[k]*((float)rate/step)));
    for(int64_t pos=0;pos<frames;pos+=substep) {
        int64_t end=pos+substep;if(end>frames)end=frames;
        float power[9]={0};
        for(int64_t i=pos;i<end;i++){
            float x=pcm[i*channels];
            if(channels==2)x=(x+pcm[i*channels+1])*.5f;
            for(int k=0;k<9;k++){
                float y=k<8?process_vector_order(&filters[k],x):process_fma(&filters[k],x);
                power[k]=fmaf(y,y,power[k]);
            }
        }
        /* Classic RMS buffers a partial short frame across reads. The first
           callback in a read carries the completed frame's END timestamp;
           other complete frames carry their START. This asymmetry is visible
           in native 0x10229217c..1ec versus 0x10229242c..480. */
        int64_t timestamp=(pos%OVERVIEW_READ_FRAMES==0 ||
                           pos/OVERVIEW_READ_FRAMES!=(end-1)/OVERVIEW_READ_FRAMES)
                          ?end:pos;
        if(timestamp>=step*(done+1)){
            for(int k=0;k<3;k++){
                envelope[k]=accum[k]>=envelope[k]?accum[k]:fmaf(alpha[k],accum[k]-envelope[k],envelope[k]);
                out[done*3+k]=envelope[k];accum[k]=0;
            }
            done++;
        }
        for(int k=0;k<9;k++)if(k!=6)
            accum[k/3]+=sqrtf(k<8?power[k]*(1.f/substep):power[k]/substep)/6.f;
    }
    while(done<count){
        for(int k=0;k<3;k++){
            envelope[k]=accum[k]>=envelope[k]?accum[k]:fmaf(alpha[k],accum[k]-envelope[k],envelope[k]);
            out[done*3+k]=envelope[k];accum[k]=0;
        }
        done++;
    }
    return done;
}
