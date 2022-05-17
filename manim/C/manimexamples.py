# render via: python3 -m manim <name of File>.py <name of Scene>
# animated gif via: ffmpeg -i media/videos/<name of File>/1080p60/<name of Scene>.mp4 -r 15 media/videos/<name of File>/1080p60/<name of Scene>.gif

from manim import *

class CompileExample1(Scene):  
    def rect_text(self, text, x, y, color=WHITE, opacity=0, scale=0.25):
        label1 = Text(text)
        label1.scale(scale)
        label1.bg = SurroundingRectangle(label1, color=color, fill_opacity=opacity)
        group1 = VGroup(label1, label1.bg)
        group1.shift(x)
        group1.shift(y)
        self.play(FadeIn(group1))
        return group1, label1
    
    def make_rect_animation(self, width, height, x, y, newx, newy, scale, color=YELLOW, delay=2, opacity=0.5):
        rect1 = Rectangle(height=height, width=width, color=color)
        rect1.set_fill(color, opacity=opacity)
        rect1.shift(y)
        rect1.shift(x)
        self.play(FadeIn(rect1))
        self.wait(delay)
        rect1.generate_target()
        rect1.target.shift(newx)
        rect1.target.shift(newy)
        rect1.target.scale(scale)
        self.play(MoveToTarget(rect1))
        self.wait(delay)
        self.remove(rect1)
        
    def construct(self):  
        # Memory Layout Table 
        # https://docs.manim.community/en/stable/reference/manim.mobject.table.Table.html
        memlayout = [["stack"], ["heap"], ["bss"], ["data"], ["text"]]
        memtable = Table(memlayout, include_outer_lines=True)
        
        memtable.add_highlighted_cell((0,0), color=YELLOW)
        memtable.add_highlighted_cell((1,0), color=TEAL)
        memtable.add_highlighted_cell((2,0), color=GREEN)
        memtable.add_highlighted_cell((3,0), color=BLUE)
        memtable.add_highlighted_cell((4,0), color=PINK)
        
        memtable.shift(3 * RIGHT)
        
        # Code Listing
        # https://docs.manim.community/en/stable/reference/manim.mobject.svg.code_mobject.Code.html
        listing = Code("csum/dynamicsum.c",     
            tab_width=4,
            background_stroke_width=1,
            background_stroke_color=WHITE,
            insert_line_no=True,
            style=Code.styles_list[15],
            background="window",
            language="cpp",
        )
        
        listing.shift(3 * LEFT)
        
        # Draw
        self.add(listing)
        self.add(memtable)
        self.wait(2)
        
        # Animate
        # https://talkingphysics.wordpress.com/2018/06/14/creating-text-manim-series-part-4/
        self.make_rect_animation(3.25, 0.35, 2.35 * LEFT, 1.15 * UP, 5.5 * RIGHT, 0.35 * DOWN, 0.75) # malloc a
        group1, label1 = self.rect_text("malloc(sizeof(int))", 6 * RIGHT, 1 * UP) # what is the address? what is its size?
        
        self.make_rect_animation(3.25, 0.35, 2.35 * LEFT, 0.85 * UP, 5.5 * RIGHT, 0.05 * DOWN, 0.75) # malloc b
        group2, label2 = self.rect_text("malloc(sizeof(int))", 6 * RIGHT, 1.4 * UP) # what is the address? what is its size?
        
        self.make_rect_animation(1, 0.35, 4.9 * LEFT, 1.15 * UP, 7 * RIGHT, 1.95 * UP, 1) # int* a
        group3, label3 = self.rect_text("int* a", 6 * RIGHT, 3.1 * UP) # what is the address? what is the value? what happens to stack data when a function returns, and how is this different from heap data?
        
        self.make_rect_animation(1, 0.35, 4.9 * LEFT, 0.85 * UP, 7.05 * RIGHT, 2.25 * UP, 1) # int* b
        group4, label4 = self.rect_text("int* b", 6 * RIGHT, 2.7 * UP) # what is the address? what is the value? what happens to stack data when a function returns, and how is this different from heap data?
        
        self.make_rect_animation(3.75, 0.35, 2.42 * LEFT, 1.45 * DOWN, 5.3 * RIGHT, 0.5 * UP, 0.6) # "Five plus two is"
        group5, label5 = self.rect_text("Five plus...", 6 * RIGHT, 1.15 * DOWN)
        
        self.make_rect_animation(1.5, 0.35, 5.15 * LEFT, 2.15 * UP, 8 * RIGHT, 1.8 * DOWN, 0.8) # int sum
        group6, label6 = self.rect_text("int sum", 6 * RIGHT, 0.25 * UP)
        
        self.make_rect_animation(6.5, 5.5, 2.55 * LEFT, 0.9 * DOWN, 4.5 * RIGHT, 1.6 * DOWN, 0.1) # code
        group7, label7 = self.rect_text("int main(void) {\n...\n    return 0;\n}", 6 * RIGHT, 2.5 * DOWN) # when you access a and b, what accesses take place to get to the heap?  what parts of your code could access a and b, and what parts could access the malloc'ed data?
        
        # Clean Up
        self.wait(2)
        
        self.remove(group1, label1)
        self.remove(group2, label2)
        self.remove(group3, label3)
        self.remove(group4, label4)
        self.remove(group5, label5)
        self.remove(group6, label6)
        self.remove(group7, label7)
