import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, it, expect, vi } from 'vitest'
import { Questions } from './Questions'

const question = { id: 'units', title: 'Единицы STL', reason: 'Нужны для размеров', options: ['mm', 'cm'], affected_actions: ['select_parameters'], answer: null }
describe('T07 questions', () => {
  it('does not submit a preselected answer', () => {
    const answer = vi.fn(); render(<Questions questions={[question]} onAnswer={answer} pending={false}/>)
    expect(answer).not.toHaveBeenCalled()
  })
  it.each(['mm', 'cm', 'Не знаю'])('accepts explicit %s', async value => {
    const answer = vi.fn(); render(<Questions questions={[question]} onAnswer={answer} pending={false}/>)
    await userEvent.click(screen.getByRole('button', {name:value, exact:true}))
    await userEvent.click(screen.getByRole('button', {name:'Отправить ответы'}))
    expect(answer).toHaveBeenCalledWith({units:value})
  })
  it('supports an open answer', async () => {
    const answer = vi.fn(); render(<Questions questions={[question]} onAnswer={answer} pending={false}/>)
    await userEvent.type(screen.getByLabelText('Свой ответ'), 'inch')
    await userEvent.click(screen.getByRole('button', {name:'Отправить ответы'}))
    expect(answer).toHaveBeenCalledWith({units:'inch'})
  })
  it('does not repeat unknown answers', () => {
    render(<Questions questions={[{...question,answer:'Не знаю'}]} onAnswer={vi.fn()} pending={false}/>)
    expect(screen.queryByText('Отправить ответы')).not.toBeInTheDocument()
  })
})
