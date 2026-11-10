\NeedsTeXFormat{LaTeX2e}
\ProvidesClass{imt_pres}
\DeclareOption*{\PassOptionsToClass{\CurrentOption}{beamer}}
\ProcessOptions\relax
\LoadClass[aspectratio=169,9pt]{beamer}
\usepackage[newPxFont,fullfooter,sectionpages]{customIMTbeamer/beamerthemeimt}
\usepackage[utf8x]{inputenc}
\usepackage{pgfplots}
\pgfplotsset{compat=1.14}
\usepackage[thicklines]{cancel}
\usepackage{setspace}
\usepackage{blindtext}
\usepackage[euler-digits,euler-hat-accent]{eulervm}
% \usepackage{showframe}
\usepackage{array}
\usepackage{colortbl}
\usepackage{etoolbox}
\usepackage{tabularray}
\usepackage{moresize}

%==========================
%= BACKGROUND OF TITLE PAGE
%==========================

\newcommand{\imttitlepage}{
    \setbeamertemplate{headline}{} 
	\usebackgroundtemplate{
    	\begin{tikzpicture}[very thick,top color=white,bottom color=gray]
    	% \fill[white] (0,0) rectangle (\paperwidth,\paperheight);
    	\fill[white] (0,0) rectangle (\paperwidth,\paperheight);
    	\fill[imtDarkBlue] (\paperheight,\paperheight) -- (\paperwidth,\paperheight) -- (\paperwidth,0) -- cycle;
        % \fill[white] (0,.8\paperheight) rectangle (\paperwidth,\paperheight);
    	\fill[color=imtRed] (\paperwidth-.42\paperheight,.11\paperheight) -- (\paperwidth,.11\paperheight) -- (\paperwidth,.54\paperheight) -- cycle;
        \fill[color=imtBlue] (0,0) -- (.35\paperheight,0) -- (0,.35\paperheight) -- cycle;
        \node[anchor=north west, inner sep=0] (logo_imt) at (.1\paperheight, .9\paperheight) {\includegraphics[height=.16\paperheight]{customIMTbeamer/logos/logo_imt_ales_rf.png}};

        \draw[black, thin] (.239\paperheight,.11\paperheight) -- (\paperwidth, .11\paperheight);
        \fill[color=white] (.239\paperheight,.109\paperheight) -- (\paperwidth, .109\paperheight) -- (\paperwidth, 0) -- ( .4\paperheight, 0) -- cycle;

        \node (logos) at (.95\paperwidth, .01\paperheight)[anchor=south east, black, thick]{\includegraphics[height=.06\paperheight]{customIMTbeamer/logos/Logo2IA.png}};
        
        % \draw[gray!50, thin, step=.1\paperheight] (current page.south west) grid (current page.north east);
    	\end{tikzpicture}
    }
    \removefootline
	\maketitle
    \usebackgroundtemplate{}
    
    \addfootline 
    \addheadline
}

\newenvironment{imttoc}{
    \setbeamertemplate{headline}{} 
	\usebackgroundtemplate{
    	\begin{tikzpicture}[very thick,top color=white,bottom color=gray]
    	\fill[white] (0,0) rectangle (\paperwidth,\paperheight);
        \fill[imtGrey] (0,\paperheight) -- (.7\paperheight,\paperheight) -- (0,.3\paperheight) -- cycle;
    	\fill[imtBlue] (0,0) -- (.45\paperheight,0) -- (0,.45\paperheight) -- cycle;
        \fill[color=imtRed] (.925\paperwidth,.5\paperheight) -- (\paperwidth,\paperheight/2+.15\paperheight) -- (\paperwidth,\paperheight/2-.15\paperheight) -- cycle;
    	\end{tikzpicture}
        % \node[draw=black, yshift=10em, xshift=10em] (Outline) at (.1\paperheight, .1\paperheight) {\color{imtDarkBlue} \large Outline};
    }
	\begin{frame}[plain]
     {\bfseries\usebeamerfont{frametitle}\Huge\color{imtDarkBlue} Outline}
    \hfill\minipage[c][.7\paperheight][c]{.6\linewidth}{}
    % \framed
    }
	{
    % \endframed
    \endminipage\hspace{2em}
    \end{frame}
    \usebackgroundtemplate{}
    }


\newcommand{\imtconclusion}[4]{
    \setbeamertemplate{headline}{} 
	\usebackgroundtemplate{
    	\begin{tikzpicture}[very thick,top color=white,bottom color=gray]
    	\fill[white] (0,0) rectangle (\paperwidth,\paperheight);

        \fill[color=imtBlue] (\paperwidth,.95\paperheight) -- (\paperwidth,0.35\paperheight) -- (.65\paperwidth,0.35\paperheight) -- cycle;
        
        \fill[color=imtRed] (.8\paperwidth,.25\paperheight) -- (.95\paperwidth,.25\paperheight) -- (.95\paperwidth,.54\paperheight) -- cycle;
        
        \node[anchor=north west, inner sep=0] (logo_imt) at (.1\paperheight, .9\paperheight) {\includegraphics[height=.14\paperheight]{customIMTbeamer/logos/logo_imt_ales_rf.png}};

        \draw[imtRed, thin] (0,0.35\paperheight) -- (.65\paperwidth, 0.35\paperheight) -- (.45\paperwidth,0);

        
        \node[ anchor=south west,xshift=2em, yshift=2em] (contact) {
        \begin{minipage}{.4\paperwidth}\raggedright
            {\bfseries \large \color{imtBlue} #2} 
            
            \vspace{-.5em}
            \tikz{\draw[imtBlue, line width=.02mm] (0, 0) -- (2.5, 0);}
            \vskip .3em
            \footnotesize #3 \vskip .2em
            #4
        \end{minipage}
        };

        \node[yshift=-21em] (logos) at (.95\paperwidth, .85\paperheight)[anchor=east, black, thick]{\includegraphics[height=.06\paperheight]{customIMTbeamer/logos/Logo2IA.png}};

        % \draw[gray!50, thin, step=.1\paperheight] (current page.south west) grid (current page.north east);
    	\end{tikzpicture}
    }

    \removefootline
    \begin{frame}{}
    \hfill \begin{minipage}{.6\paperwidth}
    {\color{imtBlue}\HUGE #1}
    \end{minipage} \hfill
    \end{frame}
    \usebackgroundtemplate{}

    
    \addfootline 
    \addheadline
}