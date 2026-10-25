% !TeX program = xelatex
% 数据与计算发展前沿（中英文）投稿模板，依据文件夹中 202608 Word 版本。
\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{dcfp}[2026/10/12 Word-derived manuscript template]
\LoadClass[UTF8,fontset=none,10pt,a4paper]{ctexart}
\RequirePackage{fontspec}
\RequirePackage{geometry}
\geometry{paperwidth=210.0086mm,paperheight=297.0036mm,
  left=31.75mm,right=31.75mm,top=21.9781mm,bottom=25.4mm,
  headheight=0bp,headsep=0bp,footskip=17.4978mm}
\RequirePackage{graphicx,xcolor,booktabs,tabularx,multicol,enumitem}
\RequirePackage{amsmath,amssymb,titlesec,caption,changepage,eso-pic}
\RequirePackage[super,sort&compress]{natbib}
\RequirePackage[hidelinks,unicode]{hyperref}
% fonts.tex 可指定用户合法持有的原字体；本类不分发商业字体。
\InputIfFileExists{fonts.tex}{}{}
\providecommand\WordSongFont{}
\providecommand\WordHeiFont{}
\providecommand\WordKaiFont{}
\providecommand\WordFangFont{}
\ifx\WordSongFont\empty
  \IfFontExistsTF{SimSun}{\renewcommand\WordSongFont{SimSun}}{
    \IfFontExistsTF{Songti SC}{\renewcommand\WordSongFont{Songti SC}}{
      \renewcommand\WordSongFont{FandolSong-Regular}}}
\fi
\ifx\WordHeiFont\empty
  \IfFontExistsTF{SimHei}{\renewcommand\WordHeiFont{SimHei}}{
    \IfFontExistsTF{Heiti SC}{\renewcommand\WordHeiFont{Heiti SC}}{
      \renewcommand\WordHeiFont{FandolHei-Regular}}}
\fi
\ifx\WordKaiFont\empty
  \IfFontExistsTF{KaiTi}{\renewcommand\WordKaiFont{KaiTi}}{
    \IfFontExistsTF{STKaiti}{\renewcommand\WordKaiFont{STKaiti}}{
      \renewcommand\WordKaiFont{FandolKai-Regular}}}
\fi
\ifx\WordFangFont\empty
  \IfFontExistsTF{FangSong}{\renewcommand\WordFangFont{FangSong}}{
    \IfFontExistsTF{STFangsong}{\renewcommand\WordFangFont{STFangsong}}{
      \renewcommand\WordFangFont{FandolFang-Regular}}}
\fi
\setCJKmainfont[AutoFakeBold=2,ItalicFont=*]{\WordSongFont}
\setCJKsansfont[AutoFakeBold=2]{\WordHeiFont}
\setCJKmonofont{\WordFangFont}
\setCJKfamilyfont{song}[AutoFakeBold=2,ItalicFont=*]{\WordSongFont}
\setCJKfamilyfont{hei}[AutoFakeBold=2]{\WordHeiFont}
\setCJKfamilyfont{kai}[AutoFakeBold=2]{\WordKaiFont}
\setCJKfamilyfont{fang}{\WordFangFont}
\providecommand\songti{\CJKfamily{song}}
\providecommand\heiti{\CJKfamily{hei}}
\providecommand\kaishu{\CJKfamily{kai}}
\providecommand\fangsong{\CJKfamily{fang}}
\IfFontExistsTF{Times New Roman}{\setmainfont{Times New Roman}}{
  \setmainfont{Liberation Serif}}
\IfFontExistsTF{Arial}{\setsansfont{Arial}}{\setsansfont{TeX Gyre Heros}}
\renewcommand\normalsize{\fontsize{10bp}{15bp}\selectfont}
\setlength\parindent{20bp}
\setlength\parskip{0bp}
\setlength\columnsep{7.5318mm} % 样例 427 twip
\setlength\multicolsep{0bp}
\setlength\premulticols{30bp}
\setlength\postmulticols{0bp}
\raggedbottom
\pagestyle{empty}
\ctexset{section={format=\heiti\fontsize{10.5bp}{15.6bp}\selectfont,
  name={},number=\arabic{section},aftername=\hspace{0.5em},
  beforeskip=8bp,afterskip=8bp,indent=0pt},
  subsection={format=\heiti\fontsize{9bp}{15.6bp}\selectfont,
  number=\thesection.\arabic{subsection},aftername=\hspace{0.5em},
  beforeskip=3.9bp,afterskip=3.9bp,indent=0pt},
  subsubsection={format=\songti\fontsize{9bp}{15.6bp}\selectfont,
  number=\thesubsection.\arabic{subsubsection},aftername=\hspace{0.5em},
  beforeskip=0bp,afterskip=0bp,indent=0pt}}
\setcounter{secnumdepth}{3}
\setlist[enumerate,1]{label=（\arabic*）,leftmargin=2em,labelsep=0pt,
  itemsep=0pt,parsep=0pt,topsep=0pt}
\newcommand\WordCircled[1]{{\fontencoding{OT1}\fontfamily{cmr}\selectfont
  \textcircled{\scriptsize #1}}}
\setlist[enumerate,2]{label=\protect\WordCircled{\arabic*},
  leftmargin=2em,labelsep=.3em,itemsep=0pt,parsep=0pt,topsep=0pt}
\DeclareCaptionFont{wordcaption}{\fontsize{8bp}{11bp}\selectfont}
\captionsetup{font=wordcaption,labelfont=normalfont,labelsep=quad,hypcap=false,
  justification=centering,skip=4bp}
\renewcommand\figurename{图}
\renewcommand\tablename{表}
\newcommand\bicaption[3]{\caption[#2]{#2\\#1~\csname the\@captype\endcsname\quad #3}}
\newcommand\figcaption[2]{\bicaption{Fig.}{#1}{#2}}
\newcommand\tabcaption[2]{\bicaption{Table}{#1}{#2}}
% 原 Word 页面边框：距纸边 24 bp，线宽 0.5 bp。可在正文调用关闭命令。
\newif\ifwordpageborder
\wordpagebordertrue
\newcommand\DisableWordPageBorder{\wordpageborderfalse}
\AddToShipoutPictureFG{\ifwordpageborder
  \AtPageLowerLeft{\setlength\unitlength{1bp}%
    \put(24,24){\color{black}\linethickness{0.5bp}%
      \framebox(\LenToUnit{\dimexpr\paperwidth-48bp\relax},
        \LenToUnit{\dimexpr\paperheight-48bp\relax}){}}}
  \fi}
\newcommand\funding[1]{\gdef\dcfp@funding{#1}}
\newcommand\correspondence[1]{\gdef\dcfp@correspondence{#1}}
\funding{}
\correspondence{}
% 首栏为单栏标题区；页脚注记绘制于页面固定位置。此处按单行注记高度
% （9bp 字面、13bp 行距）预留正文可用高度，保证标题区末行与注记不重叠。
\newcommand\FirstPageNotes{\enlargethispage{0bp}\AddToShipoutPictureFG*{%
  \AtPageLowerLeft{\setlength\unitlength{1mm}%
    \put(31.75,17.4978){\parbox[b]{\textwidth}{\fontsize{9bp}{13bp}\selectfont
      \ifx\dcfp@funding\empty\else{\heiti 基金项目：}\dcfp@funding\par\fi
      \ifx\dcfp@correspondence\empty\else{\heiti *通信作者：}\dcfp@correspondence\par\fi}}}}}
\newcommand\CNTitle[1]{\par\vspace{16bp}{\centering\heiti
  \fontsize{14bp}{18bp}\selectfont #1\par}}
\newcommand\CNAuthors[1]{\par\vspace{8bp}{\centering\kaishu
  \fontsize{10.5bp}{15.6bp}\selectfont #1\par}\vspace{12bp}}
\newcommand\CNAffiliation[1]{{\centering\songti
  \fontsize{9bp}{15.6bp}\selectfont #1\par}}
\newcommand\CNAbstract[1]{\par\vspace{15.6bp}{\kaishu
  \fontsize{9bp}{15.6bp}\selectfont\noindent{\heiti 摘\quad 要：}#1\par}}
\newcommand\CNKeywords[1]{\par\vspace{15.6bp}{\kaishu
  \fontsize{9bp}{15.6bp}\selectfont\noindent{\heiti 关键词：}#1\par}}
\newcommand\ENTitle[1]{\par\vspace{12bp}{\centering\bfseries
  \fontsize{14bp}{18bp}\selectfont #1\par}\vspace{5bp}}
\newcommand\ENAuthors[1]{\par\vspace{11bp}{\centering
  \fontsize{10.5bp}{15.6bp}\selectfont #1\par}\vspace{9bp}}
\newcommand\ENAffiliation[1]{{\centering\itshape
  \fontsize{9bp}{15.6bp}\selectfont #1\par}}
\newcommand\ENAbstract[1]{\par\vspace{15.6bp}{\fontsize{9bp}{15.6bp}\selectfont
  \noindent\textbf{Abstract: }#1\par}\vspace{12bp}}
\newcommand\ENKeywords[1]{{\fontsize{9bp}{15.6bp}\selectfont
  \noindent\textbf{Keywords: }#1\par}\vspace{14.5bp}}
% Continuous native two-column body; all figures/tables stay in one column.
\newenvironment{PaperBody}{\twocolumn\normalsize\raggedbottom}{}
\newenvironment{columnfigure}{\begin{figure}[!htbp]\centering}{\end{figure}}
\newenvironment{columntable}{\begin{table}[!htbp]\centering
  \fontsize{8bp}{11bp}\selectfont}{\end{table}}
\newcommand\WordMathSize{7.5}
\newcommand\AprilMathSizes{\renewcommand\WordMathSize{9}%
  \DeclareMathSizes{9.03375}{9.03375}{5.520625}{4.516875}}
\newenvironment{wordequation}{\begingroup\fontsize{\WordMathSize bp}{13bp}\selectfont
  \begin{equation}}{\end{equation}\endgroup}
\renewcommand\refname{参考文献：}
\renewcommand\bibsection{\section*{\refname}}
\renewcommand\bibfont{\songti\fontsize{7.5bp}{11bp}\selectfont}
\setlength\bibsep{0pt}
\setlength\bibhang{1.7em}
\setcitestyle{square}
\renewcommand\@biblabel[1]{[#1]}
% 第一作者与通信作者分别调用；真实照片插入 25×35 mm 框。
\newcommand\AuthorProfile[5]{\par\medskip\noindent
  \begin{minipage}[t]{25mm}\vspace{0pt}\centering
    \IfFileExists{#1}{\includegraphics[width=25mm,height=35mm,keepaspectratio]{#1}}{
      \fbox{\parbox[c][34mm][c]{\dimexpr25mm-2\fboxsep-2\fboxrule\relax}{\centering\fontsize{9bp}{13bp}\selectfont 作者照片}}}
  \end{minipage}\hfill
  \begin{minipage}[t]{\dimexpr\linewidth-28mm\relax}\vspace{0pt}
    \fontsize{9bp}{13bp}\selectfont #2\par #3\par
    \textbf{E-mail: }\url{#4}\par
  \end{minipage}\par\smallskip
  {\fontsize{9bp}{13bp}\selectfont #5\par}}
\AtBeginDocument{\normalsize}
\endinput
